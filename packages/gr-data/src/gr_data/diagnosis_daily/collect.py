"""单日供应商采集与离线归一化；调用方只提供只读数据库连接。"""

from __future__ import annotations

import logging
import re
from contextlib import contextmanager
from copy import deepcopy
from datetime import date, datetime, timedelta, timezone
from typing import Any, LiteralString, cast

import pandas as pd
import polars as pl
import psycopg

from gr_data.common import contracts
from gr_data.common.parquet import write_parquet
from gr_data.common.paths import RawPaths
from gr_data.common.ricequant_risk_quality import validate_daily_risk
from gr_data.common.ricequant_symbol_intervals import (
    HISTORY_SYMBOL_RULES_VERSION,
    resolve_symbol_intervals,
    symbol_rule_evidence,
    symbol_rule_hash,
)
from gr_data.common.ricequant_universe import (
    build_universe_provider,
    load_metadata_snapshot,
    reference_input_codes,
)
from gr_data.common.trading_status import event_flags, resolve_trading_status
from gr_data.config.ricequant import RicequantImportOptions
from gr_data.config.ricequant_risk import RiskOptions
from gr_data.ingest.base import IngestContext
from gr_data.ingest.ricequant.riskmodel import (
    _dynamic_coverage,
    _normalize,
    _publication_quality,
    _storage_values,
)
from gr_data.ingest.tushare.adapter import TushareAdapter
from gr_data.ingest.tushare.financial import normalize_annual_roe
from gr_data.ingest.tushare.importers.market import (
    AdjFactorTsImporter,
    StockBars1dImporter,
    ValuationImporter,
)
from gr_data.ingest.tushare.importers.reference import CalendarImporter, InstrumentsImporter
from gr_data.ingest.tushare.industry import (
    industry_changes,
    normalize_industry,
    validate_missing_closures,
)
from gr_data.ingest.tushare.stock_scope import b_share_mask
from gr_data.ingest.tushare.suspensions import read_suspensions
from gr_data.raw.base import RawContext
from gr_data.raw.ricequant.fetchers.supplements import _check_quota
from gr_data.raw.ricequant.riskmodel import read_bundles, run_risk_raw
from gr_data.raw.tushare.context import TushareRawContext
from gr_data.raw.tushare.fetchers import REGISTRY
from gr_data.raw.tushare.fetchers.reference import (
    STOCK_BASIC_FIELDS,
    read_open_days,
    require_calendar_range,
)

from .evidence import file_hash, write_json


log = logging.getLogger(__name__)


def collect_tushare(client: Any, paths: RawPaths, day: date, previous: date) -> datetime:
    """仅沪深股票所需原件；财务按明确公告日增量，保留空响应凭据。"""
    stock = pd.concat(
        [
            client.query_all("stock_basic", list_status=s, fields=STOCK_BASIC_FIELDS)
            for s in ("L", "D", "P")
        ],
        ignore_index=True,
    )
    if stock.empty:
        raise ValueError("Missing stock master source")
    write_parquet(stock, paths.dataset_file("tushare", "instruments", "stock"))
    ctx = TushareRawContext(
        paths=paths, start_date=int(day.strftime("%Y%m%d")), end_date=int(day.strftime("%Y%m%d"))
    )
    # 日历额外取历史窗口及未来缓冲；其他抓取器严格限定单日。
    calendar_ctx = TushareRawContext(
        paths=paths, start_date=int((day - timedelta(days=450)).strftime("%Y%m%d"))
    )
    REGISTRY["calendar"](client, calendar_ctx).fetch()
    for name in ("daily", "adj_factor", "daily_basic", "stk_limit", "suspend_d"):
        REGISTRY[name](client, ctx).fetch()
    nodes = client.query_all("index_classify", src="SW2021", level="L1")
    if nodes.empty:
        raise ValueError("Missing SW2021 industry nodes")
    write_parquet(nodes, paths.dataset_file("tushare", "industry", "nodes"))
    members = []
    for code in nodes["index_code"]:
        rows = client.query_all("index_member_all", l1_code=code, is_new="N")
        current = client.query_all("index_member_all", l1_code=code, is_new="Y")
        members.extend([rows, current])
    write_parquet(
        pd.concat(members, ignore_index=True), paths.dataset_file("tushare", "industry", "members")
    )
    fiscal = []
    for stamp in pd.date_range(previous + timedelta(days=1), day):
        rows = client.query_all(
            "fina_indicator_vip",
            ann_date=stamp.strftime("%Y%m%d"),
            fields="ts_code,end_date,ann_date,roe_waa,update_flag",
        )
        if not rows.empty and not rows["ann_date"].eq(stamp.strftime("%Y%m%d")).all():
            raise ValueError("Financial supplier ignored announcement-date filter")
        fiscal.append(rows)
    frame = pd.concat(fiscal, ignore_index=True) if fiscal else pd.DataFrame()
    if frame.empty:
        frame = pd.DataFrame(columns=["ts_code", "end_date", "ann_date", "roe_waa", "update_flag"])
    write_parquet(frame, paths.dataset_file("tushare", "fina_indicator", "increment"))
    observed = datetime.now(timezone.utc)
    write_json(
        paths.dataset_dir("tushare", "daily_capture") / "complete.json",
        {"day": day, "previous": previous, "observed_at": observed},
    )
    return observed


def collect_annual_backfill(
    client: Any, paths: RawPaths, symbols: list[str], day: date
) -> tuple[pl.DataFrame, datetime]:
    """新在市证券没有年度基线时补最近两年；不把旧公告遗漏在日增量之外。"""
    frames = []
    for symbol in sorted(symbols):
        if re.fullmatch(r"[0-9]{6}\.(SH|SZ)", symbol) is None:
            raise ValueError("Unsupported annual bootstrap symbol")
        for year in (day.year - 1, day.year - 2):
            period = f"{year}1231"
            frame = client.query_all(
                "fina_indicator",
                ts_code=symbol,
                period=period,
                fields="ts_code,end_date,ann_date,roe_waa,update_flag",
            )
            if not frame.empty and (
                not frame["ts_code"].eq(symbol).all()
                or not frame["end_date"].astype(str).eq(period).all()
            ):
                raise ValueError("Annual bootstrap source ignored identity or period filter")
            if frame.empty:
                frame = pd.DataFrame(
                    columns=["ts_code", "end_date", "ann_date", "roe_waa", "update_flag"]
                )
            write_parquet(
                frame,
                paths.dataset_file(
                    "tushare", "fina_indicator", f"annual-bootstrap/{symbol}/{period}"
                ),
            )
            frames.append(frame)
    observed = datetime.now(timezone.utc)
    raw = pd.concat(frames, ignore_index=True)
    write_json(
        paths.dataset_dir("tushare", "daily_capture") / "annual-bootstrap.json",
        {
            "symbols": symbols,
            "observed_at": observed,
            "rows": len(raw),
            "years": [day.year - 1, day.year - 2],
        },
    )
    return pl.from_pandas(raw), observed


class _PreparationConnection:
    """读取原连接，审计INSERT缓存在内存；其他SQL一律拒绝。"""

    def __init__(self, conn: psycopg.Connection) -> None:
        self.conn = conn
        self.audits: list[tuple] = []

    def execute(self, query: LiteralString, params: Any = None) -> Any:
        if query.lstrip().startswith("INSERT INTO ops.data_quality_check"):
            self.audits.append(tuple(params))
            return None
        if not query.lstrip().startswith("SELECT "):
            raise ValueError("Offline normalization attempted a non-read statement")
        with self.conn.cursor() as cur:
            cur.execute(query, params)
            rows = cur.fetchall()
        self._rows = _PreparedRows(rows)
        return self._rows

    def executemany(self, query: LiteralString, params: Any) -> None:
        for row in params:
            self.execute(query, row)

    @contextmanager
    def cursor(self):
        yield self

    def fetchall(self) -> Any:
        return self._rows.fetchall()


class _PreparedRows:
    def __init__(self, rows: list) -> None:
        self.rows = rows

    def fetchall(self) -> list:
        return self.rows


class _OfflineBars(StockBars1dImporter):
    """复用严格行情规则；状态取同批已校验事件，审计延后至发布事务。"""

    mapping: dict[str, int]
    events: pd.DataFrame
    listings: dict[str, date]
    audits: list[tuple[str, str, str]]

    def _id_map(self) -> dict[str, int]:
        return self.mapping

    def _stock_listing_dates(self, codes: list[str]) -> dict[str, date]:
        return {code: self.listings[code] for code in codes if code in self.listings}

    def _trading_status(self, market: pd.DataFrame, months: list[str]) -> pd.Series:
        keys = ["instrument_id", "trading_day"]
        evidence = market[["instrument_id", "dt"]].rename(columns={"dt": "trading_day"})
        flags = event_flags(self.events, keys)
        evidence = evidence.merge(flags, on=keys, how="left")
        evidence["has_bar"] = True
        evidence["covered"] = True
        result = resolve_trading_status(evidence.drop(columns=keys))
        return pd.Series(result.to_numpy(), index=market.index)


class _OfflineValuation(ValuationImporter):
    mapping: dict[str, int]

    def _id_map(self) -> dict[str, int]:
        return self.mapping


class _OfflineAdj(AdjFactorTsImporter):
    mapping: dict[str, int]

    def _id_map(self) -> dict[str, int]:
        return self.mapping


def normalize_tushare(
    conn: psycopg.Connection, paths: RawPaths, day: date, observed: datetime
) -> tuple[dict[str, pl.DataFrame], dict, dict[str, int], date]:
    """在只读事务中冻结身份与历史覆盖；不调用有提交副作用的 importer.run。"""
    ctx = IngestContext(paths, months=(day.strftime("%Y-%m"),))
    adapter = TushareAdapter(paths, ctx.months)
    raw = pd.read_parquet(paths.dataset_file("tushare", "instruments", "stock"))
    raw = raw.loc[raw.ts_code.str.endswith((".SH", ".SZ")) & ~b_share_mask(raw.ts_code)]
    if raw.ts_code.duplicated().any():
        raise ValueError("Duplicate stock master identities")
    master = InstrumentsImporter(cast("psycopg.Connection", None), ctx)._build_stock(raw)
    metadata = load_metadata_snapshot(conn)
    by_symbol = {r["symbol"]: r["instrument_id"] for r in metadata["instruments"]}
    # 新身份先冻结候选ID，阶段B锁表后验证并显式插入；序列只在真正新增时推进。
    maximum = conn.execute(
        "SELECT greatest(coalesce(max(instrument_id),0), (SELECT last_value "
        "FROM meta.instruments_instrument_id_seq)) FROM meta.instruments"
    ).fetchone()
    if maximum is None:
        raise ValueError("Instrument sequence is unavailable")
    for index, symbol in enumerate(sorted(set(master.symbol) - set(by_symbol)), 1):
        by_symbol[symbol] = maximum[0] + index
    master.insert(0, "instrument_id", master.symbol.map(by_symbol))
    metadata["instruments"] = master[
        ["instrument_id", "symbol", "exchange", "list_date", "delist_date", "status"]
    ].to_dict("records")
    for row in metadata["instruments"]:
        for key in ("list_date", "delist_date"):
            row[key] = str(row[key]) if row[key] is not None else None
    aliases = {(r["source"], r["source_symbol"]): r for r in metadata["aliases"]}
    for symbol, iid in by_symbol.items():
        aliases["tushare", symbol] = {
            "source": "tushare",
            "source_symbol": symbol,
            "instrument_id": iid,
        }
    metadata["aliases"] = list(aliases.values())
    active = master.loc[
        (master.list_date <= day) & (master.delist_date.isna() | (master.delist_date > day))
    ]
    symbol_ids = dict(zip(active.symbol, active.instrument_id, strict=True))
    calendars = []
    for source, exchange in (("SSE", "XSHG"), ("SZSE", "XSHE")):
        cal = pd.read_parquet(paths.dataset_file("tushare", "calendar", source))
        require_calendar_range(cal, day - timedelta(days=420), day + timedelta(days=7), source)
        opened = read_open_days(cal, source)
        if day not in opened:
            raise ValueError("Target is not an open trading day")
        if source == "SSE":
            history_start = sorted(d for d in opened if d <= day)[-254]
        calendars.append(
            CalendarImporter(cast("psycopg.Connection", None), ctx)._build_one(cal, exchange)
        )
    events, coverage = read_suspensions(paths, ctx.months or (), required=True)
    if set(coverage.trading_day) != {day}:
        raise ValueError("Suspension source does not prove the target day")
    events = events.loc[events.ts_code.isin(by_symbol)].copy()
    events["instrument_id"] = events.ts_code.map(by_symbol)
    events = events.rename(columns={"ts_code": "source_symbol", "trade_date": "trading_day"})
    events["source"] = "tushare"
    events = events[list(contracts.STOCK_SUSPEND_EVENT.columns)]
    overrides = {}
    for dataset in ("daily", "adj_factor", "stk_limit", "daily_basic"):
        df = adapter.read_all_months(dataset)
        if df.empty:
            raise ValueError(f"Missing target-day source: {dataset}")
        if not df.trade_date.astype(str).eq(day.strftime("%Y%m%d")).all():
            raise ValueError("Daily artifact contains another trading day")
        overrides[dataset, day.strftime("%Y-%m")] = df.loc[df.ts_code.isin(by_symbol)]
    offline_adapter = TushareAdapter(paths, ctx.months, overrides=overrides)
    frames = {}
    prepared_conn = _PreparationConnection(conn)
    for cls, contract in (
        (_OfflineBars, contracts.bar_1d("stock")),
        (_OfflineAdj, contracts.ADJ_FACTOR_TS),
        (_OfflineValuation, contracts.VALUATION_1D),
    ):
        importer = cls(cast("psycopg.Connection", cast("object", prepared_conn)), ctx)
        importer.mapping = by_symbol
        importer._tushare_adapter = offline_adapter
        if isinstance(importer, _OfflineBars):
            importer.events = events
            importer.listings = dict(zip(master.symbol, master.list_date, strict=True))
        df = importer._build_strict()
        if importer._check_quality(df):
            raise ValueError("Canonical daily data failed importer quality checks")
        frames[contract.qualified] = pl.from_pandas(df)
    bars = frames["market.stock_bar_1d"]
    bar_ids = set(bars["instrument_id"])
    full_suspended = set(
        event_flags(events, ["instrument_id", "trading_day"])
        .query("full_suspend and not intraday_suspend and not resumed")
        .instrument_id
    )
    missing = set(symbol_ids.values()) - bar_ids - full_suspended
    if missing:
        raise ValueError(f"Missing daily bars without full suspension evidence: {len(missing)}")
    val_ids = set(frames["fundamental.valuation_1d"]["instrument_id"])
    if bar_ids - val_ids:
        raise ValueError("Missing valuation for traded stocks")
    category = master[["instrument_id", "list_date", "delist_date"]].rename(
        columns={"list_date": "in_date", "delist_date": "out_date"}
    )
    category = category.assign(
        asset_category="equity", market="cn_a", available_at=observed, source="tushare"
    )
    industry = normalize_industry(
        pl.read_parquet(paths.dataset_file("tushare", "industry", "nodes")),
        pl.read_parquet(paths.dataset_file("tushare", "industry", "members")),
        symbol_ids=symbol_ids,
        as_of=day,
        observed_at=observed,
    )
    from psycopg.rows import dict_row

    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            "SELECT instrument_id,scheme_code,level,industry_code,in_date,out_date,"
            "available_at,source FROM classify.instrument_industry "
            "WHERE scheme_code='sw2021' AND level=1 AND instrument_id=ANY(%s)",
            (sorted(symbol_ids.values()),),
        )
        existing_industry = cur.fetchall()
    validate_missing_closures(
        existing_industry, industry_changes(existing_industry, industry), industry
    )
    fiscal = normalize_annual_roe(
        pl.read_parquet(paths.dataset_file("tushare", "fina_indicator", "increment")),
        symbol_ids=symbol_ids,
        as_of=day,
        observed_at=observed,
    )
    frames.update(
        {
            "meta.instruments": pl.from_pandas(master),
            "meta.symbol_map": pl.DataFrame(
                [r for r in metadata["aliases"] if r["source"] == "tushare"]
            ),
            "meta.trading_calendar": pl.from_pandas(pd.concat(calendars, ignore_index=True)),
            "market.stock_suspend_event": pl.from_pandas(events),
            "market.stock_suspend_coverage": pl.from_pandas(coverage),
            "classify.instrument_category": pl.from_pandas(category),
            "classify.industry_node": industry.nodes,
            "classify.instrument_industry": industry.members,
            "industry_closed": industry.closed_members
            if industry.closed_members is not None
            else industry.members.clear(),
            "fundamental.indicator_q": fiscal,
        }
    )
    write_json(paths.dataset_dir("tushare", "daily_capture") / "audits.json", prepared_conn.audits)
    return frames, metadata, symbol_ids, history_start


def current_alias_snapshot(metadata: dict, day: date) -> tuple[dict, dict]:
    """只排除已验证且早已过期的非v4别名；未知别名继续交严格门禁拒绝。"""
    rules = resolve_symbol_intervals(metadata, HISTORY_SYMBOL_RULES_VERSION)
    production = symbol_rule_evidence("cn_stock_code_intervals_v4")
    retained_old = {r["old_source_symbol"] for r in production["rules"]}
    excluded = []
    snapshot = deepcopy(metadata)
    aliases = []
    for row in snapshot["aliases"]:
        rule = rules.get(row["instrument_id"])
        if (
            rule is not None
            and row["source"] == "tushare"
            and row["source_symbol"] == rule["old_source_symbol"]
            and row["source_symbol"] not in retained_old
            and day >= date.fromisoformat(rule["old_valid_to_exclusive"])
        ):
            excluded.append({**row, "rule": rule})
        else:
            aliases.append(row)
    snapshot["aliases"] = aliases
    return snapshot, {
        "target_day": str(day),
        "expired_aliases": excluded,
        "rules_hash": symbol_rule_hash(HISTORY_SYMBOL_RULES_VERSION),
    }


def validate_risk_identities(manifest: dict, metadata: dict, day: date) -> None:
    """完整候选集合须与本库当日在市身份一致，缺项证券同样不能跨库错配。"""
    expected = {
        row["instrument_id"]: row["symbol"]
        for row in metadata["instruments"]
        if row["list_date"] is not None
        and date.fromisoformat(str(row["list_date"])) <= day
        and (row["delist_date"] is None or date.fromisoformat(str(row["delist_date"])) > day)
    }
    actual = {row["instrument_id"]: row["canonical_symbol"] for row in manifest["coverage"]}
    if actual != expected:
        raise ValueError(
            "Risk candidate identities differ from target database; capture a new risk observation"
        )


def collect_risk(
    client: Any, paths: RawPaths, day: date, options: RiskOptions, metadata: dict
) -> dict:
    """SDK 3.8.1 的命名轴由既有 raw v2 校验器显式对齐；此处不登记PG检查点。"""
    metadata, alias_scope = current_alias_snapshot(metadata, day)
    write_json(paths.dataset_dir("ricequant", "daily_capture") / "alias-scope.json", alias_scope)
    reference = client.risk_reference(
        reference_input_codes(metadata), quota_guard=lambda: _check_quota(client, 0.1)
    )
    if options.symbol_rules_version is None:
        raise ValueError("Risk symbol rules must be explicit")
    provider = build_universe_provider(
        metadata,
        reference,
        universe_policy=options.universe_policy,
        mapping_version=options.mapping_version,
        symbol_rules=symbol_rule_evidence(options.symbol_rules_version),
    )
    run_risk_raw(
        client,
        RawContext(paths),
        options,
        RicequantImportOptions(datasets={"rq_risk_model": options}),
        mode="init",
        universe_provider=provider,
        capture_callback=lambda m: write_json(
            paths.dataset_dir("ricequant", "daily_capture") / "manifest.json", m
        ),
    )
    bundles = list(read_bundles(paths, options))
    if len(bundles) != 1 or bundles[0][0]["day"] != str(day):
        raise ValueError("Risk capture must contain exactly the requested trading day")
    manifest, frames = bundles[0]
    validate_risk_identities(manifest, metadata, day)
    coverage = _dynamic_coverage(manifest, frames, options)
    values = _normalize(frames, options)
    storage = _storage_values(values)
    quality = validate_daily_risk(
        storage["exposure"], storage["covariance"], storage["specific_risk"].reshape(-1)
    )
    quality.update(_publication_quality(manifest))
    if not quality["publication_eligible"]:
        raise ValueError(f"Risk publication gate failed: {quality['publication_reasons']}")
    ids = sorted({r["instrument_id"] for r in coverage if r["status"] == "included"})
    write_json(
        paths.dataset_dir("ricequant", "daily_capture") / "preflight.json",
        {
            "quality": quality,
            "security_ids": ids,
            "observation_id": manifest["observation_id"],
            "files": {
                p.relative_to(paths.root).as_posix(): file_hash(p)
                for p in paths.provider_dir("ricequant").rglob("*.parquet")
            },
        },
    )
    return {"quality": quality, "security_ids": ids, "manifest": manifest}
