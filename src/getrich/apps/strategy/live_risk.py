"""Live risk monitoring and alerting for signal production."""

from __future__ import annotations

import asyncio
import json
import logging
import smtplib
import urllib.request
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Protocol, runtime_checkable

from getrich.apps.web.metrics import LIVE_ALERTS_EMITTED_TOTAL
from getrich_backtest import get_shanghai_tz
from getrich_backtest.risk import RiskConfig
from getrich_backtest.time import require_shanghai_aware


if TYPE_CHECKING:
    from getrich_backtest.strategy.context import AccountView


logger = logging.getLogger(__name__)

_DECIMAL_ZERO = Decimal("0")


# ---------------------------------------------------------------------------
# RiskAlert
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RiskAlert:
    """A structured risk alert triggered during live monitoring."""

    severity: str  # "warning" | "critical"
    check: str  # "margin_call" | "liquidation" | "leverage" | "concentration"
    reason: str
    details: dict[str, object] | None = None
    triggered_at: datetime | None = None

    def __post_init__(self) -> None:
        if self.triggered_at is not None:
            require_shanghai_aware(self.triggered_at)
        if self.severity not in ("warning", "critical"):
            raise ValueError("RiskAlert severity must be 'warning' or 'critical'")
        if not self.check.strip():
            raise ValueError("RiskAlert check must be non-empty")
        if not self.reason.strip():
            raise ValueError("RiskAlert reason must be non-empty")


# ---------------------------------------------------------------------------
# Alert channels
# ---------------------------------------------------------------------------


@runtime_checkable
class AlertChannel(Protocol):
    """Protocol for alert delivery channels.

    Implementations must be safe to call from ``async`` contexts and
    must not raise exceptions — failures should be logged internally.
    """

    async def send(self, alert: RiskAlert) -> None: ...


class LoggingAlertChannel:
    """Deliver alerts through the Python logging system.

    ``warning``-severity alerts are emitted at WARNING level;
    ``critical``-severity alerts are emitted at ERROR level.
    Structured *alert.details* are attached to the log record as
    ``extra`` when the dict is non-empty.
    """

    def __init__(self, name: str | None = None) -> None:
        self._logger = logging.getLogger(name if name is not None else f"{__name__}.channel")

    async def send(self, alert: RiskAlert) -> None:
        msg = f"[{alert.check}] {alert.reason}"
        extra: dict[str, object] | None = (
            {"risk_alert_details": alert.details} if alert.details else None
        )
        if alert.severity == "critical":
            self._logger.error(msg, extra=extra)
        else:
            self._logger.warning(msg, extra=extra)


class WebhookAlertChannel:
    """Deliver alerts as JSON via HTTP POST to a configurable webhook URL.

    Parameters
    ----------
    url : str
        Webhook endpoint URL.
    timeout : float
        Request timeout in seconds (default 10).
    headers : dict | None
        Additional HTTP headers.  ``Content-Type: application/json`` is
        set by default.
    name : str
        Logical name for log messages (default ``"webhook"``).
    """

    def __init__(
        self,
        url: str,
        *,
        timeout: float = 10.0,
        headers: dict[str, str] | None = None,
        name: str = "webhook",
    ) -> None:
        self._url = url
        self._timeout = timeout
        self._headers: dict[str, str] = dict(headers) if headers else {}
        self._headers.setdefault("Content-Type", "application/json; charset=utf-8")
        self._name = name
        self._logger = logging.getLogger(f"{__name__}.{name}")

    # -------------------------------------------------------------- serialize

    @staticmethod
    def _serialize(alert: RiskAlert) -> dict[str, object]:
        return {
            "severity": alert.severity,
            "check": alert.check,
            "reason": alert.reason,
            "details": alert.details or {},
            "triggered_at": alert.triggered_at.isoformat() if alert.triggered_at else None,
        }

    # -------------------------------------------------------------- send

    async def send(self, alert: RiskAlert) -> None:
        payload = json.dumps(self._serialize(alert), default=str, ensure_ascii=False)
        data = payload.encode("utf-8")
        req = urllib.request.Request(
            self._url,
            data=data,
            headers=self._headers,
            method="POST",
        )
        try:
            await asyncio.to_thread(urllib.request.urlopen, req, timeout=self._timeout)
        except Exception:
            self._logger.warning(
                "Webhook delivery to %s failed for alert [%s]",
                self._url,
                alert.check,
                exc_info=True,
            )


class EmailAlertChannel:
    """Deliver alerts via SMTP email.

    Parameters
    ----------
    smtp_host : str
        SMTP server hostname.
    smtp_port : int
        SMTP server port (default 587 for STARTTLS).
    username : str
        SMTP authentication username.
    password : str
        SMTP authentication password.
    from_addr : str
        Email ``From:`` address.
    to_addrs : list[str]
        List of ``To:`` recipient addresses.
    use_tls : bool
        Whether to use STARTTLS (default True).
    name : str
        Logical name for log messages (default ``"email"``).
    """

    def __init__(
        self,
        smtp_host: str,
        *,
        smtp_port: int = 587,
        username: str,
        password: str,
        from_addr: str,
        to_addrs: list[str],
        use_tls: bool = True,
        name: str = "email",
    ) -> None:
        self._host = smtp_host
        self._port = smtp_port
        self._username = username
        self._password = password
        self._from = from_addr
        self._to = list(to_addrs)
        self._use_tls = use_tls
        self._name = name
        self._logger = logging.getLogger(f"{__name__}.{name}")

    # -------------------------------------------------------------- build email

    def _build_message(self, alert: RiskAlert) -> str:
        lines: list[str] = []
        lines.append(f"Subject: [GetRich {alert.severity.upper()}] {alert.check}: {alert.reason}")
        lines.append(f"From: {self._from}")
        lines.append(f"To: {', '.join(self._to)}")
        lines.append("Content-Type: text/plain; charset=utf-8")
        lines.append("")
        lines.append(f"Severity:    {alert.severity}")
        lines.append(f"Check:       {alert.check}")
        lines.append(f"Reason:      {alert.reason}")
        if alert.triggered_at:
            lines.append(f"Triggered:   {alert.triggered_at.isoformat()}")
        if alert.details:
            lines.append("Details:")
            for k, v in alert.details.items():
                lines.append(f"  {k}: {v}")
        return "\n".join(lines)

    # -------------------------------------------------------------- send

    async def send(self, alert: RiskAlert) -> None:
        msg = self._build_message(alert)

        def _deliver() -> None:
            if self._use_tls:
                server = smtplib.SMTP(self._host, self._port, timeout=15)
                server.starttls()
            else:
                server = smtplib.SMTP_SSL(self._host, self._port, timeout=15)
            try:
                server.login(self._username, self._password)
                server.sendmail(self._from, self._to, msg.encode("utf-8"))
            finally:
                server.quit()

        try:
            await asyncio.to_thread(_deliver)
        except Exception:
            self._logger.warning(
                "Email delivery to %s failed for alert [%s]",
                self._to,
                alert.check,
                exc_info=True,
            )


# ---------------------------------------------------------------------------
# LiveRiskMonitor
# ---------------------------------------------------------------------------


class LiveRiskMonitor:
    """Evaluate risk constraints against live account state.

    Parameters
    ----------
    config : RiskConfig | None
        Risk thresholds.  Defaults to ``RiskConfig()`` when omitted
        (margin-call at 100% maintenance, liquidation at 80%).
    channels : Sequence[AlertChannel] | None
        Alert delivery channels.  When omitted alerts are produced
        but not delivered — the caller must inspect the returned
        ``RiskAlert`` list.
    """

    def __init__(
        self,
        config: RiskConfig | None = None,
        *,
        channels: Sequence[AlertChannel] | None = None,
    ) -> None:
        self.config = config if config is not None else RiskConfig()
        self._channels = tuple(channels) if channels else ()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def check_account_health(
        self,
        account: AccountView,
        last_prices: dict[str, Decimal],
        *,
        now: datetime | None = None,
    ) -> list[RiskAlert]:
        """Run all configured risk checks against *account*.

        Returns a list of ``RiskAlert`` objects.  An empty list means
        that no risk threshold is currently breached.

        When *now* is omitted the current time in ``Asia/Shanghai`` is
        used as the alert timestamp.
        """
        ts = now if now is not None else datetime.now(get_shanghai_tz())
        alerts: list[RiskAlert] = []

        # Margin / liquidation (independent of last_prices)
        alerts.extend(self._check_margin(account, ts))

        # Leverage (uses last_prices to compute equity/exposure)
        if (
            self.config.max_leverage is not None
            and (alert := self._check_leverage(account, last_prices, ts)) is not None
        ):
            alerts.append(alert)

        # Concentration (uses last_prices per symbol)
        if self.config.max_position_concentration is not None:
            alerts.extend(self._check_concentration(account, last_prices, ts))

        return alerts

    async def send_alerts(self, alerts: list[RiskAlert]) -> None:
        """Deliver *alerts* through all configured channels."""
        for alert in alerts:
            # Increment the per-severity counter BEFORE the channel
            # send so even a totally-failing channel is observable.
            # The send itself is wrapped in try/except below so a
            # single channel failure does not stop the others.
            LIVE_ALERTS_EMITTED_TOTAL.labels(alert.severity).inc()
            for channel in self._channels:
                try:
                    await channel.send(alert)
                # silent-fail-ok: one failing channel must not
                # block the others from receiving the same
                # alert; the channel-level error is already
                # logged inside channel.send().
                except Exception:
                    logger.warning(
                        "Alert channel %s failed to send alert %s",
                        type(channel).__name__,
                        alert.check,
                        exc_info=True,
                    )

    # ------------------------------------------------------------------
    # Private: margin / liquidation
    # ------------------------------------------------------------------

    def _check_margin(self, account: AccountView, ts: datetime) -> list[RiskAlert]:
        maintenance = account.maintenance_margin
        if maintenance <= _DECIMAL_ZERO or account.available_cash is None:
            return []

        available = account.available_cash
        alerts: list[RiskAlert] = []

        # Liquidation (checked first — more severe)
        liq_ratio = available / maintenance
        if liq_ratio < self.config.liquidation_threshold:
            alerts.append(
                RiskAlert(
                    severity="critical",
                    check="liquidation",
                    reason=(
                        f"available_cash ({available:.2f}) / "
                        f"maintenance_margin ({maintenance:.2f}) = "
                        f"{float(liq_ratio):.2%} < "
                        f"liquidation_threshold ({float(self.config.liquidation_threshold):.0%})"
                    ),
                    details={
                        "available_cash": str(available),
                        "maintenance_margin": str(maintenance),
                        "ratio": str(liq_ratio),
                        "threshold": str(self.config.liquidation_threshold),
                    },
                    triggered_at=ts,
                )
            )

        # Margin call
        if liq_ratio < self.config.margin_call_threshold:
            alerts.append(
                RiskAlert(
                    severity="warning",
                    check="margin_call",
                    reason=(
                        f"available_cash ({available:.2f}) / "
                        f"maintenance_margin ({maintenance:.2f}) = "
                        f"{float(liq_ratio):.2%} < "
                        f"margin_call_threshold ({float(self.config.margin_call_threshold):.0%})"
                    ),
                    details={
                        "available_cash": str(available),
                        "maintenance_margin": str(maintenance),
                        "ratio": str(liq_ratio),
                        "threshold": str(self.config.margin_call_threshold),
                    },
                    triggered_at=ts,
                )
            )

        return alerts

    # ------------------------------------------------------------------
    # Private: leverage
    # ------------------------------------------------------------------

    def _check_leverage(
        self,
        account: AccountView,
        last_prices: dict[str, Decimal],
        ts: datetime,
    ) -> RiskAlert | None:
        if self.config.max_leverage is None:
            return None

        equity = _compute_equity(account, last_prices)
        if equity <= _DECIMAL_ZERO:
            return RiskAlert(
                severity="critical",
                check="leverage",
                reason="equity is zero or negative — leverage limit exceeded",
                triggered_at=ts,
            )

        exposure = _compute_gross_exposure(account, last_prices)
        lev = exposure / equity
        if lev > self.config.max_leverage:
            return RiskAlert(
                severity="critical",
                check="leverage",
                reason=(
                    f"gross_exposure ({exposure:.2f}) / equity ({equity:.2f}) "
                    f"= {float(lev):.2f}x > max_leverage ({float(self.config.max_leverage):.1f}x)"
                ),
                details={
                    "gross_exposure": str(exposure),
                    "equity": str(equity),
                    "leverage": str(lev),
                    "max_leverage": str(self.config.max_leverage),
                },
                triggered_at=ts,
            )
        return None

    # ------------------------------------------------------------------
    # Private: concentration
    # ------------------------------------------------------------------

    def _check_concentration(
        self,
        account: AccountView,
        last_prices: dict[str, Decimal],
        ts: datetime,
    ) -> list[RiskAlert]:
        if self.config.max_position_concentration is None:
            return []

        equity = _compute_equity(account, last_prices)
        if equity <= _DECIMAL_ZERO:
            positions = account.positions or {}
            return [
                RiskAlert(
                    severity="warning",
                    check="concentration",
                    reason=(
                        f"equity is zero or negative — {symbol} position concentration is undefined"
                    ),
                    details={"symbol": symbol},
                    triggered_at=ts,
                )
                for symbol in positions
            ]

        alerts: list[RiskAlert] = []
        positions = account.positions or {}
        cap = self.config.max_position_concentration

        for symbol in positions:
            price = last_prices.get(symbol, _DECIMAL_ZERO)
            if price <= _DECIMAL_ZERO:
                continue
            notional = abs(positions[symbol].qty) * price
            conc = notional / equity
            if conc > cap:
                alerts.append(
                    RiskAlert(
                        severity="warning",
                        check="concentration",
                        reason=(
                            f"{symbol} position ({notional:.2f}) / equity ({equity:.2f}) "
                            f"= {float(conc):.1%} > max_concentration ({float(cap):.0%})"
                        ),
                        details={
                            "symbol": symbol,
                            "notional": str(notional),
                            "equity": str(equity),
                            "concentration": str(conc),
                            "max_concentration": str(cap),
                        },
                        triggered_at=ts,
                    )
                )
        return alerts


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _compute_equity(
    account: AccountView,
    last_prices: dict[str, Decimal],
) -> Decimal:
    """Cash + unrealised PnL from current positions."""
    equity = account.cash
    positions = account.positions or {}
    for symbol, pos in positions.items():
        price = last_prices.get(symbol, _DECIMAL_ZERO)
        if price > _DECIMAL_ZERO:
            equity += pos.qty * price
    return equity


def _compute_gross_exposure(
    account: AccountView,
    last_prices: dict[str, Decimal],
) -> Decimal:
    """Sum of absolute notional values across all positions."""
    total = _DECIMAL_ZERO
    positions = account.positions or {}
    for symbol, pos in positions.items():
        price = last_prices.get(symbol, _DECIMAL_ZERO)
        if price > _DECIMAL_ZERO:
            total += abs(pos.qty) * price
    return total


__all__ = [
    "AlertChannel",
    "EmailAlertChannel",
    "LiveRiskMonitor",
    "LoggingAlertChannel",
    "RiskAlert",
    "WebhookAlertChannel",
]
