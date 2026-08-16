"""Public entry points for the GetRich backtesting framework."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from contextlib import suppress
from datetime import datetime
from decimal import Decimal

import polars as pl

from gr_backtest.account import (
    Account,
    Position,
    daily_settle,
    get_settlement_prices,
)
from gr_backtest.calendar import Calendar, Session
from gr_backtest.cost import FeeModel, SlippageModel
from gr_backtest.data import (
    BarLoader,
    DataFrameBarLoader,
    DuckDBBarLoader,
    PgBarLoader,
    validate_bar_schema,
    validate_corp_actions_schema,
)
from gr_backtest.data.resample import resample_bars
from gr_backtest.exceptions import (
    AccountError,
    BacktestError,
    BarSchemaError,
    CorporateActionError,
    DataLoadError,
    ExecutionError,
    OrderIntentError,
    StrategyError,
    TimezoneError,
)
from gr_backtest.execution import Fill, NextBarMatchingModel, Order, OrderStatus
from gr_backtest.margin import MarginCalculator
from gr_backtest.result import BacktestResult, CombinedResult
from gr_backtest.risk import LiquidationEvent, RiskConfig, RiskManager
from gr_backtest.runconfig import RunConfig
from gr_backtest.strategy import (
    AccountView,
    BarContext,
    Context,
    HistoryView,
    OrderIntent,
    PositionView,
    Strategy,
    TakeProfitStopLoss,
    set_ctx_calendar,
    set_ctx_corp_actions,
    set_ctx_factors,
    set_ctx_instruments,
)
from gr_backtest.time import (
    ensure_shanghai_aware,
    get_shanghai_tz,
    normalize_datetime_range,
    require_shanghai_aware,
)
from gr_backtest.types import (
    FREQ_TO_MINUTES,
    AssetClass,
    Exchange,
    Frequency,
    Money,
    OrderType,
    Quantity,
    Side,
    Symbol,
    TimeInForce,
)


_DECIMAL_ZERO = Decimal("0")


class Backtest:
    """Main backtest runner entry point.

    Supports both single-strategy (via ``strategy=`` parameter) and
    multi-strategy (via ``add_strategy()``) modes.

    Examples
    --------
    >>> bt = Backtest(bar_loader=..., symbols=["A"], start=..., end=...,
    ...               initial_cash=Decimal("100000"))
    >>> bt.add_strategy(StratA(), capital_weight=Decimal("0.6"))
    >>> bt.add_strategy(StratB(), capital_weight=Decimal("0.4"))
    >>> result = bt.run()  # returns CombinedResult
    >>> result.strategy("StratA").tear_sheet()
    """

    def __init__(
        self,
        *,
        strategy: Strategy | None = None,
        bar_loader: BarLoader,
        symbols: Sequence[str],
        start: datetime,
        end: datetime,
        initial_cash: Decimal,
        freq: str = Frequency.ONE_DAY.value,
        extra_freqs: Sequence[str] | None = None,
        execution_lag_bars: int = 1,
        run_id: str = "default",
        fee_model: FeeModel | None = None,
        slippage_model: SlippageModel | None = None,
        calendar: Calendar | None = None,
        risk_config: RiskConfig | None = None,
        sessions: Sequence[Session] | None = None,
        strategy_params: Mapping[str, object] | None = None,
    ) -> None:
        if not isinstance(initial_cash, Decimal):
            raise BacktestError("initial_cash must be decimal.Decimal")
        if initial_cash < _DECIMAL_ZERO:
            raise BacktestError("initial_cash must be non-negative")
        if not symbols:
            raise BacktestError("symbols must be non-empty")
        if not run_id.strip():
            raise BacktestError("run_id must be non-empty")

        self.bar_loader = bar_loader
        self.symbols = tuple(symbols)
        self.start, self.end = normalize_datetime_range(start, end)
        self.initial_cash = initial_cash
        self.freq = freq
        self._raw_extra_freqs = extra_freqs
        self.matching_model = NextBarMatchingModel(
            execution_lag_bars=execution_lag_bars,
            fee_model=fee_model,
            slippage_model=slippage_model,
        )
        self.run_id = run_id
        self.calendar = calendar
        self.risk_config = risk_config
        self.sessions = tuple(sessions) if sessions is not None else None
        self.strategy_params = dict(strategy_params) if strategy_params is not None else None
        self._risk_manager = RiskManager(risk_config) if risk_config is not None else None
        self._strategies: list[tuple[Strategy, Decimal]] = []
        if strategy is not None:
            self._strategies.append((strategy, Decimal("1.0")))

        # Build config placeholder; updated in run()
        self.config = RunConfig(
            run_id=run_id,
            strategy_name=strategy.name if strategy else "_none",
            symbols=self.symbols,
            start=self.start,
            end=self.end,
            initial_cash=initial_cash,
            freq=freq,
            extra_freqs=tuple(extra_freqs) if extra_freqs else (),
            execution_lag_bars=execution_lag_bars,
            strategy_params=self.strategy_params,
            risk_config=risk_config.to_dict() if risk_config is not None else None,
            created_at=datetime.now(get_shanghai_tz()),
        )

    def add_strategy(
        self,
        strategy: Strategy,
        capital_weight: Decimal = Decimal("1.0"),
    ) -> None:
        """Register a strategy with its capital weight.

        Parameters
        ----------
        strategy : Strategy
            A strategy instance.
        capital_weight : Decimal
            Relative capital weight (will be normalised to sum 1.0
            across all strategies).
        """
        if capital_weight <= _DECIMAL_ZERO:
            raise BacktestError("capital_weight must be positive")
        names = {s.name for s, _ in self._strategies}
        if strategy.name in names:
            raise BacktestError(f"strategy name '{strategy.name}' already exists")
        self._strategies.append((strategy, capital_weight))

    def run(self) -> BacktestResult:
        """Run the configured backtest."""
        if not self._strategies:
            raise BacktestError("at least one strategy is required")
        if len(self._strategies) == 1:
            return self._run_single()
        return self._run_multi()

    def _build_extra_bars(
        self,
        bars: pl.DataFrame,
        extra_freqs: tuple[str, ...],
        *,
        source_freq: str | None = None,
    ) -> dict[str, pl.DataFrame]:
        """Build extra-frequency bars, optionally session-aligned.

        *source_freq* defaults to ``self.freq`` when not provided.
        """
        sf = source_freq or self.freq
        extra_bars: dict[str, pl.DataFrame] = {}
        for ef in extra_freqs:
            if self.sessions is None:
                ef_bars = self.bar_loader.load_bars(self.symbols, self.start, self.end, freq=ef)
            else:
                ef_bars = resample_bars(
                    bars,
                    ef,
                    source_freq=sf,
                    sessions=self.sessions,
                )
            extra_bars[ef] = validate_bar_schema(ef_bars)
        return extra_bars

    @staticmethod
    def _resolve_strategy_freqs(
        strategies: list[tuple[Strategy, object]],
        default_freq: str,
    ) -> dict[str, str]:
        """Resolve each strategyʼs effective frequency.

        *default_freq* is the backtestʼs primary frequency, used when a
        strategy does not declare its own ``freq``.
        """
        result: dict[str, str] = {}
        for s, _ in strategies:
            sf = getattr(s, "freq", None) or default_freq
            if not Frequency.is_valid(sf):
                raise BacktestError(
                    f"strategy '{s.name}' has invalid freq {sf!r}. "
                    f"Valid: {sorted(Frequency.all_values())}"
                )
            result[s.name] = sf
        return result

    # ------------------------------------------------------------------
    # Single-strategy fast path (identical to pre-P4c behaviour)
    # ------------------------------------------------------------------

    def _run_single(self) -> BacktestResult:
        strategy, _weight = self._strategies[0]
        bars = self.bar_loader.load_bars(self.symbols, self.start, self.end, freq=self.freq)
        bars = validate_bar_schema(bars)

        extra_freqs_tuple: tuple[str, ...] = (
            tuple(self._raw_extra_freqs) if self._raw_extra_freqs else ()
        )

        extra_bars = self._build_extra_bars(bars, extra_freqs_tuple)

        instruments_df = self._load_instruments()
        margin_calc = (
            MarginCalculator(instruments_df)
            if instruments_df is not None and not instruments_df.is_empty()
            else None
        )

        account = Account(
            initial_cash=self.initial_cash,
            margin_calculator=margin_calc,
        )
        orders: list[Order] = []
        fills: list[Fill] = []
        equity_rows: list[dict[str, object]] = []
        sub_equity_rows: dict[str, list[dict[str, object]]] | None = None
        last_prices: dict[str, Decimal] = {}
        prev_equity = self.initial_cash
        total_fees_so_far = _DECIMAL_ZERO
        fills_before_index = 0

        self.config = RunConfig(
            run_id=self.run_id,
            strategy_name=strategy.name,
            symbols=self.symbols,
            start=self.start,
            end=self.end,
            initial_cash=self.initial_cash,
            freq=self.freq,
            extra_freqs=extra_freqs_tuple,
            execution_lag_bars=self.matching_model.execution_lag_bars,
            strategy_params=self.strategy_params,
            risk_config=self.risk_config.to_dict() if self.risk_config is not None else None,
            created_at=self.config.created_at,
        )

        cal = self._load_or_build_calendar()
        corp_actions_df = self._load_corp_actions()
        factors_dict = self._load_factors()
        ctx = Context(
            now=self.start,
            run_id=self.run_id,
            account=account.view(),
        )
        if instruments_df is not None:
            set_ctx_instruments(ctx, instruments_df)
        if cal is not None:
            set_ctx_calendar(ctx, cal)
        if corp_actions_df is not None:
            set_ctx_corp_actions(ctx, corp_actions_df)
        if factors_dict is not None:
            set_ctx_factors(ctx, factors_dict)
        strategy.setup(ctx)

        dts = bars.select(pl.col("dt").unique().sort().alias("dt"))["dt"].to_list()
        if cal is not None:
            dts = [dt for dt in dts if cal.is_trading_date(dt.date())]
        for bar_index, current_dt in enumerate(dts):
            if not isinstance(current_dt, datetime):
                raise BacktestError("bar dt must be a datetime")
            require_shanghai_aware(current_dt)
            current_bar = bars.filter(pl.col("dt") == current_dt)

            prev_realized_pnl = account.total_realized_pnl

            self._match_eligible_orders(
                orders=orders,
                fills=fills,
                bar=current_bar,
                account=account,
                bar_index=bar_index,
            )

            new_fills_this_bar = fills[fills_before_index:]
            fills_before_index = len(fills)
            trading_pnl = account.total_realized_pnl - prev_realized_pnl
            for fill in new_fills_this_bar:
                total_fees_so_far += fill.fee

            # Apply corporate actions for this bar date
            self._apply_corp_actions(account, current_dt, corp_actions_df)

            self._update_last_prices(current_bar, last_prices)

            # Daily settlement for margined positions (futures)
            if account._margin_calculator is not None:
                settle_prices = get_settlement_prices(current_bar, last_prices)
                daily_settle(account, settle_prices, current_dt)
                self._apply_risk_controls(account, last_prices, current_dt)

            current_equity = account.equity(last_prices)
            equity_change = current_equity - prev_equity
            prev_equity = current_equity
            mtm_pnl = equity_change - trading_pnl

            visible_history = bars.filter(pl.col("dt") <= current_dt)

            # Build extra frequency histories (expanding window per freq)
            extra_history_dict: dict[str, HistoryView] = {}
            for ef, ef_bars_data in extra_bars.items():
                ef_visible = ef_bars_data.filter(pl.col("dt") <= current_dt)
                extra_history_dict[ef] = HistoryView(ef_visible)

            ctx = BarContext(
                now=current_dt,
                run_id=self.run_id,
                account=account.view(),
                bar=current_bar,
                history=HistoryView(visible_history),
                extra_history=extra_history_dict or None,
            )
            if cal is not None:
                set_ctx_calendar(ctx, cal)
            if factors_dict is not None:
                set_ctx_factors(ctx, factors_dict)
            if corp_actions_df is not None:
                set_ctx_corp_actions(ctx, corp_actions_df)
            intents = self._collect_order_intents(strategy.on_bar(ctx))
            for intent in intents:
                orders.append(
                    Order(
                        order_id=f"{self.run_id}-order-{len(orders) + 1}",
                        intent=intent,
                        strategy_name=strategy.name,
                        created_dt=current_dt,
                        created_index=bar_index,
                        eligible_index=bar_index + self.matching_model.execution_lag_bars,
                    )
                )

            equity_rows.append(
                {
                    "dt": current_dt,
                    "cash": account.cash,
                    "equity": current_equity,
                    "trading_pnl": trading_pnl,
                    "mtm_pnl": mtm_pnl,
                    "total_fees": total_fees_so_far,
                    "gross_exposure": account.gross_exposure(last_prices),
                }
            )

            # Track per-sub-account equity when sub-accounts are present.
            if account.sub_accounts:
                if sub_equity_rows is None:
                    sub_equity_rows = {name: [] for name in account.sub_accounts}
                sa_map = account.sub_account_equity_map(last_prices)
                for name in account.sub_accounts:
                    sub_equity_rows[name].append(
                        {
                            "dt": current_dt,
                            "equity": str(sa_map.get(name, _DECIMAL_ZERO)),
                        }
                    )

        for order in orders:
            order.expire()

        strategy.teardown(Context(now=self.end, run_id=self.run_id, account=account.view()))

        return BacktestResult(
            run_id=self.run_id,
            strategy_name=strategy.name,
            initial_cash=self.initial_cash,
            config=self.config,
            orders=tuple(orders),
            fills=tuple(fills),
            final_account=account.view(),
            equity_curve=pl.DataFrame(equity_rows),
            bars=bars,
            extra_bars=extra_bars or None,
            sub_account_equity=(
                {name: pl.DataFrame(rows) for name, rows in sub_equity_rows.items()}
                if sub_equity_rows is not None
                else None
            ),
        )

    # ------------------------------------------------------------------
    # Multi-strategy path
    # ------------------------------------------------------------------

    def _run_multi(self) -> CombinedResult:
        # 1. Normalise weights
        total_weight = sum(w for _, w in self._strategies)
        normalised: list[tuple[Strategy, Decimal]] = [
            (s, w / total_weight) for s, w in self._strategies
        ]
        strategy_names = [s.name for s, _ in normalised]

        # 1a. Resolve per-strategy frequencies → determine base_freq
        strategy_freqs = self._resolve_strategy_freqs(normalised, self.freq)
        base_freq = min(strategy_freqs.values(), key=lambda f: FREQ_TO_MINUTES[f])
        strategy_freqs_tuples = tuple((name, freq) for name, freq in strategy_freqs.items())

        extra_freqs_tuple_m: tuple[str, ...] = (
            tuple(self._raw_extra_freqs) if self._raw_extra_freqs else ()
        )

        self.config = RunConfig(
            run_id=self.run_id,
            strategy_name="_combined",
            strategy_names=tuple(strategy_names),
            strategy_freqs=strategy_freqs_tuples,
            symbols=self.symbols,
            start=self.start,
            end=self.end,
            initial_cash=self.initial_cash,
            freq=base_freq,
            extra_freqs=extra_freqs_tuple_m,
            execution_lag_bars=self.matching_model.execution_lag_bars,
            strategy_params=self.strategy_params,
            risk_config=self.risk_config.to_dict() if self.risk_config is not None else None,
            created_at=self.config.created_at,
        )

        instruments_df = self._load_instruments()
        margin_calc = (
            MarginCalculator(instruments_df)
            if instruments_df is not None and not instruments_df.is_empty()
            else None
        )

        # 2. Create per-strategy accounts
        from decimal import ROUND_DOWN

        accounts: dict[str, Account] = {}
        for strategy, weight in normalised:
            allocated = (self.initial_cash * weight).quantize(Decimal("0.01"), rounding=ROUND_DOWN)
            accounts[strategy.name] = Account(
                initial_cash=allocated,
                cash=allocated,
                margin_calculator=margin_calc,
            )

        # 3. Load bars at base_freq (finest granularity across all strategies)
        bars = self.bar_loader.load_bars(self.symbols, self.start, self.end, freq=base_freq)
        bars = validate_bar_schema(bars)

        extra_bars_m = self._build_extra_bars(bars, extra_freqs_tuple_m, source_freq=base_freq)

        # 3a. Pre-resample per-strategy bars + build dt alignment sets
        strategy_bars: dict[str, pl.DataFrame] = {}
        strategy_dts: dict[str, set[datetime]] = {}
        for s_name, sf in strategy_freqs.items():
            if sf == base_freq:
                s_bars = bars
            elif self.sessions is not None:
                s_bars = resample_bars(bars, sf, source_freq=base_freq, sessions=self.sessions)
            else:
                s_bars = self.bar_loader.load_bars(self.symbols, self.start, self.end, freq=sf)
                s_bars = validate_bar_schema(s_bars)
            strategy_bars[s_name] = s_bars
            strategy_dts[s_name] = set(
                s_bars.select(pl.col("dt").unique().sort().alias("dt"))["dt"].to_list()
            )

        # 3b. Per-strategy extra_bars (only frequencies coarser than the strategyʼs own freq)
        strategy_extra_bars: dict[str, dict[str, pl.DataFrame]] = {}
        for s_name, sf in strategy_freqs.items():
            sf_minutes = FREQ_TO_MINUTES[sf]
            filtered: dict[str, pl.DataFrame] = {}
            for ef_name, ef_data in extra_bars_m.items():
                if FREQ_TO_MINUTES[ef_name] > sf_minutes:
                    filtered[ef_name] = ef_data
            strategy_extra_bars[s_name] = filtered

        # 4. Per-strategy state
        per_orders: dict[str, list[Order]] = {s.name: [] for s, _ in normalised}
        per_fills: dict[str, list[Fill]] = {s.name: [] for s, _ in normalised}
        per_equity: dict[str, list[dict[str, object]]] = {s.name: [] for s, _ in normalised}
        per_prev_equity: dict[str, Decimal] = {
            s.name: accounts[s.name].initial_cash for s, _ in normalised
        }
        per_fills_before: dict[str, int] = {s.name: 0 for s, _ in normalised}
        per_total_fees: dict[str, Decimal] = {s.name: _DECIMAL_ZERO for s, _ in normalised}

        all_orders: list[Order] = []
        all_fills_list: list[Fill] = []
        last_prices: dict[str, Decimal] = {}

        # 5. Setup strategies
        cal = self._load_or_build_calendar()
        corp_actions_df = self._load_corp_actions()
        factors_dict = self._load_factors()
        for strategy, _ in normalised:
            ctx = Context(
                now=self.start,
                run_id=self.run_id,
                account=accounts[strategy.name].view(),
            )
            if instruments_df is not None:
                set_ctx_instruments(ctx, instruments_df)
            if cal is not None:
                set_ctx_calendar(ctx, cal)
            if corp_actions_df is not None:
                set_ctx_corp_actions(ctx, corp_actions_df)
            if factors_dict is not None:
                set_ctx_factors(ctx, factors_dict)
            strategy.setup(ctx)

        # 6. Bar loop — iterate at base_freq; order matching/settlement at every
        #    base_freq bar for all strategies, but on_bar() only at strategy-aligned dts.
        dts = bars.select(pl.col("dt").unique().sort().alias("dt"))["dt"].to_list()
        if cal is not None:
            dts = [dt for dt in dts if cal.is_trading_date(dt.date())]
        for bar_index, current_dt in enumerate(dts):
            if not isinstance(current_dt, datetime):
                raise BacktestError("bar dt must be a datetime")
            require_shanghai_aware(current_dt)
            current_bar = bars.filter(pl.col("dt") == current_dt)
            self._update_last_prices(current_bar, last_prices)

            for strategy, _weight in normalised:
                s_name = strategy.name
                account = accounts[s_name]
                s_orders = per_orders[s_name]
                s_fills = per_fills[s_name]
                prev_realized_pnl = account.total_realized_pnl

                self._match_eligible_orders(
                    orders=s_orders,
                    fills=s_fills,
                    bar=current_bar,
                    account=account,
                    bar_index=bar_index,
                )

                new_fills_this_bar = s_fills[per_fills_before[s_name] :]
                per_fills_before[s_name] = len(s_fills)
                trading_pnl = account.total_realized_pnl - prev_realized_pnl
                for fill in new_fills_this_bar:
                    per_total_fees[s_name] += fill.fee

                # Apply corporate actions for this bar date
                self._apply_corp_actions(account, current_dt, corp_actions_df)

                if account._margin_calculator is not None:
                    settle_prices = get_settlement_prices(current_bar, last_prices)
                    daily_settle(account, settle_prices, current_dt)
                    self._apply_risk_controls(account, last_prices, current_dt)

                current_equity = account.equity(last_prices)
                equity_change = current_equity - per_prev_equity[s_name]
                per_prev_equity[s_name] = current_equity
                mtm_pnl = equity_change - trading_pnl

                # --- on_bar gating: only fire at strategy-aligned timestamps ---
                if current_dt in strategy_dts[s_name]:
                    s_bars = strategy_bars[s_name]
                    s_current_bar = s_bars.filter(pl.col("dt") == current_dt)
                    visible_history = s_bars.filter(pl.col("dt") <= current_dt)

                    # Build extra frequency histories (per-strategy filtered, expanding window)
                    extra_history_dict_m: dict[str, HistoryView] = {}
                    for ef, ef_bars_data in strategy_extra_bars[s_name].items():
                        ef_visible = ef_bars_data.filter(pl.col("dt") <= current_dt)
                        extra_history_dict_m[ef] = HistoryView(ef_visible)

                    ctx = BarContext(
                        now=current_dt,
                        run_id=self.run_id,
                        account=account.view(),
                        bar=s_current_bar,
                        history=HistoryView(visible_history),
                        extra_history=extra_history_dict_m or None,
                    )
                    if cal is not None:
                        set_ctx_calendar(ctx, cal)
                    if factors_dict is not None:
                        set_ctx_factors(ctx, factors_dict)
                    if corp_actions_df is not None:
                        set_ctx_corp_actions(ctx, corp_actions_df)
                    intents = self._collect_order_intents(strategy.on_bar(ctx))
                    for intent in intents:
                        order = Order(
                            order_id=f"{self.run_id}-{s_name}-order-{len(s_orders) + 1}",
                            intent=intent,
                            strategy_name=s_name,
                            created_dt=current_dt,
                            created_index=bar_index,
                            eligible_index=bar_index + self.matching_model.execution_lag_bars,
                        )
                        s_orders.append(order)
                        all_orders.append(order)

                # Equity row at every base_freq bar (even when on_bar was skipped)
                per_equity[s_name].append(
                    {
                        "dt": current_dt,
                        "strategy_name": s_name,
                        "cash": account.cash,
                        "equity": current_equity,
                        "trading_pnl": trading_pnl,
                        "mtm_pnl": mtm_pnl,
                        "total_fees": per_total_fees[s_name],
                        "gross_exposure": account.gross_exposure(last_prices),
                    }
                )

        # 7. Expire all orders
        for order in all_orders:
            order.expire()

        # 8. Teardown
        for strategy, _ in normalised:
            strategy.teardown(
                Context(
                    now=self.end,
                    run_id=self.run_id,
                    account=accounts[strategy.name].view(),
                )
            )

        # 9. Build per-strategy results (each uses its own bars + filtered extras)
        per_results: dict[str, BacktestResult] = {}
        for s_name, equity_rows in per_equity.items():
            per_results[s_name] = BacktestResult(
                run_id=self.run_id,
                strategy_name=s_name,
                initial_cash=accounts[s_name].initial_cash,
                config=self.config,
                orders=tuple(per_orders[s_name]),
                fills=tuple(per_fills[s_name]),
                final_account=accounts[s_name].view(),
                equity_curve=pl.DataFrame(equity_rows),
                bars=strategy_bars[s_name],
                extra_bars=strategy_extra_bars.get(s_name) or None,
            )

        # 10. Combined equity curve
        combined_equity = pl.concat(
            [pl.DataFrame(rows) for rows in per_equity.values()],
            how="vertical",
        )

        # 11. Combined fills
        for fills in per_fills.values():
            all_fills_list.extend(fills)

        # 12. Combined final account (sum cash + positions)
        combined_cash = sum(accounts[s.name].cash for s, _ in normalised)
        combined_positions: dict[str, Decimal] = {}
        for _s_name, account in accounts.items():
            for sym, pos in account.positions.items():
                combined_positions[sym] = combined_positions.get(sym, _DECIMAL_ZERO) + pos.qty
        from gr_backtest.strategy import PositionView

        combined_pos_views = {
            sym: PositionView(symbol=sym, qty=qty) for sym, qty in combined_positions.items()
        }

        return CombinedResult(
            run_id=self.run_id,
            strategy_name="_combined",
            initial_cash=self.initial_cash,
            config=self.config,
            orders=tuple(all_orders),
            fills=tuple(all_fills_list),
            final_account=AccountView(cash=combined_cash, positions=combined_pos_views),
            equity_curve=combined_equity,
            _per_strategy_results=per_results,
        )

    def _apply_risk_controls(
        self,
        account: Account,
        last_prices: dict[str, Decimal],
        current_dt: datetime,
    ) -> None:
        """Apply configured risk checks after settlement.

        Checks the main account and each sub-account for margin calls
        and forced liquidation.  If *any* sub-account triggers a margin
        call, the main account's ``margin_call_triggered`` flag is set
        so that new exposure-increasing orders are blocked globally.
        """
        if self._risk_manager is None:
            return
        if self._risk_manager.check_margin_call(account):
            account.margin_state.margin_call_triggered = True
            account.margin_state.last_margin_call_dt = current_dt
        else:
            account.margin_state.margin_call_triggered = False
        if self._risk_manager.check_liquidation(account):
            account.margin_state.forced_liquidation_triggered = True
            self._risk_manager.liquidate_all(account, last_prices, current_dt)

        # --- Sub-account margin checks ---------------------------------------
        for sub in account.sub_accounts.values():
            maint = sub.margin_state.maintenance_margin
            if maint <= _DECIMAL_ZERO:
                continue
            # Margin call: sub-account available cash < threshold
            if sub.available_cash < maint * self._risk_manager.config.margin_call_threshold:
                account.margin_state.margin_call_triggered = True
                account.margin_state.last_margin_call_dt = current_dt
            # Liquidation: sub-account available cash < threshold
            if sub.available_cash < maint * self._risk_manager.config.liquidation_threshold:
                account.margin_state.forced_liquidation_triggered = True

    def _match_eligible_orders(
        self,
        *,
        orders: list[Order],
        fills: list[Fill],
        bar: pl.DataFrame,
        account: Account,
        bar_index: int,
    ) -> None:
        exposure_increasing_sides = {Side.BUY, Side.OPEN_LONG, Side.OPEN_SHORT}
        for order in orders:
            if order.eligible_index != bar_index:
                continue
            if (
                account.margin_state.margin_call_triggered
                and order.side in exposure_increasing_sides
            ):
                order.status = OrderStatus.REJECTED
                order.reject_reason = "margin call in effect"
                continue

            # Reserve cash for orders that need cash (buy, open_long, close_short)
            reserve_amount = Decimal("0")
            if order.side in {Side.BUY, Side.OPEN_LONG, Side.CLOSE_SHORT}:
                est_bar = bar.filter(pl.col("symbol") == order.symbol)
                if not est_bar.is_empty():
                    est_open_price = Decimal(str(est_bar.row(0, named=True)["open"]))
                    qty = order.resolve_qty(account, est_open_price)
                    if qty > 0:
                        fee_model = self.matching_model.fee_model
                        if fee_model is not None:
                            est_fee = fee_model.compute(qty, est_open_price, order.side)
                        else:
                            est_fee = Decimal("0")
                        reserve_amount = qty * est_open_price + est_fee

            has_reserved = False
            if reserve_amount > Decimal("0"):
                try:
                    account.reserve(reserve_amount)
                    has_reserved = True
                except AccountError:
                    order.status = OrderStatus.REJECTED
                    order.reject_reason = "insufficient available cash"
                    continue

            fill = self.matching_model.match(
                order,
                bar,
                account,
                fill_id=f"{self.run_id}-fill-{len(fills) + 1}",
            )
            if fill is None:
                if has_reserved:
                    account.release(reserve_amount)
                continue
            account.apply(fill)
            fills.append(fill)

    @staticmethod
    def _load_instruments_from(loader: object) -> pl.DataFrame | None:
        """Try to load instruments from a BarLoader; return None if unsupported."""
        if not hasattr(loader, "load_instruments"):
            return None
        for asset_class in ("index_future", "commodity_future", "equity_a"):
            try:
                result = loader.load_instruments(asset_class=asset_class)  # type: ignore[union-attr]
                return result if not result.is_empty() else None
            except Exception:
                continue
        return None

    def _load_instruments(self) -> pl.DataFrame | None:
        """Load instrument metadata for this backtest run."""
        return self._load_instruments_from(self.bar_loader)

    @staticmethod
    def _apply_corp_actions(
        account: Account,
        current_dt: datetime,
        corp_actions_df: pl.DataFrame | None,
    ) -> None:
        """Apply corporate actions for the current bar date to the account."""
        if corp_actions_df is None or corp_actions_df.is_empty():
            return
        today = current_dt.date()
        day_actions = corp_actions_df.filter(pl.col("ex_date") == today)
        for row in day_actions.iter_rows(named=True):
            with suppress(CorporateActionError):
                account.apply_corporate_action(
                    symbol=str(row["symbol"]),
                    action_type=str(row["action_type"]),
                    amount=row.get("amount"),
                    split_ratio=row.get("split_ratio"),
                    bonus_ratio=row.get("bonus_ratio"),
                )

    def _load_or_build_calendar(self) -> Calendar | None:
        """Load calendar from loader or return existing one."""
        if self.calendar is not None:
            return self.calendar
        if not hasattr(self.bar_loader, "load_calendar"):
            return None
        try:
            cal_df = self.bar_loader.load_calendar(
                exchange="SSE",
                start=self.start,
                end=self.end,
            )
        except Exception:
            return None
        if cal_df is None or cal_df.is_empty():
            return None
        td_rows = cal_df.filter(pl.col("is_trading_day")).iter_rows(named=True)
        from datetime import time

        trading_days = [
            datetime.combine(row["date"], time.min, tzinfo=get_shanghai_tz()) for row in td_rows
        ]
        if not trading_days:
            return None
        from gr_backtest.calendar import Calendar

        return Calendar(trading_days=tuple(trading_days))

    def _load_corp_actions(self) -> pl.DataFrame | None:
        """Load corporate actions from the bar loader."""
        if not hasattr(self.bar_loader, "load_corp_actions"):
            return None
        try:
            result = self.bar_loader.load_corp_actions(
                symbols=self.symbols,
                start=self.start,
                end=self.end,
            )
            if result.is_empty():
                return None
            return validate_corp_actions_schema(result)
        except Exception:
            return None

    def _load_factors(self) -> dict[str, pl.DataFrame] | None:
        """Load pre-computed factors from the bar loader.

        Returns a dictionary ``{factor_name → pl.DataFrame[dt, symbol, value]}``.
        """
        has_it = hasattr(self.bar_loader, "load_factors")
        if not has_it:
            return None
        try:
            df = self.bar_loader.load_factors(
                symbols=self.symbols,
                start=self.start,
                end=self.end,
            )
        except Exception:
            return None
        if df.is_empty():
            return None
        result: dict[str, pl.DataFrame] = {}
        for name, grp in df.group_by("factor"):
            key = name[0] if isinstance(name, tuple) else name
            result[key] = grp.drop("factor")
        return result

    def _collect_order_intents(
        self,
        intents: Iterable[OrderIntent] | None,
    ) -> list[OrderIntent]:
        if intents is None:
            return []
        result = list(intents)
        for intent in result:
            if not isinstance(intent, OrderIntent):
                raise StrategyError("strategy.on_bar must return OrderIntent instances")
        return result

    def _update_last_prices(
        self,
        bar: pl.DataFrame,
        last_prices: dict[str, Decimal],
    ) -> None:
        for row in bar.select(["symbol", "close"]).iter_rows(named=True):
            close = row["close"]
            price = close if isinstance(close, Decimal) else Decimal(str(close))
            last_prices[row["symbol"]] = price


__all__ = [
    "Account",
    "AccountError",
    "AccountView",
    "AssetClass",
    "Backtest",
    "CorporateActionError",
    "Backtest",
    "BacktestError",
    "BacktestResult",
    "BarContext",
    "BarLoader",
    "BarSchemaError",
    "Context",
    "DataFrameBarLoader",
    "DataLoadError",
    "DuckDBBarLoader",
    "Exchange",
    "ExecutionError",
    "Fill",
    "Frequency",
    "HistoryView",
    "LiquidationEvent",
    "Money",
    "NextBarMatchingModel",
    "Order",
    "OrderIntent",
    "OrderIntentError",
    "PgBarLoader",
    "OrderStatus",
    "OrderType",
    "Position",
    "PositionView",
    "Quantity",
    "RiskConfig",
    "RiskManager",
    "RunConfig",
    "Side",
    "Strategy",
    "StrategyError",
    "Symbol",
    "TakeProfitStopLoss",
    "TimeInForce",
    "TimezoneError",
    "ensure_shanghai_aware",
    "get_shanghai_tz",
    "normalize_datetime_range",
    "require_shanghai_aware",
    "validate_bar_schema",
]
