# INSIGHT P1 Schema Review

> Lead agent: code_dev
> Sample date: 2026-06-04
> Sample root: `/home/quant/data/insight/p1_samples`
> Status: Draft, sample-backed ETF and non-ETF fund loaders split into separate tables

## Current Design Decisions

- Local database rebuild is allowed during this P1 phase. P1 schema changes can be folded into `sql/init/backend/60_insight.sql` before the next stable commit and verified by recreating the local `getrich` database.
- ETF and ordinary fund must be separated. The `510300.SH` samples below are ETF samples even though they come from INSIGHT fund-family APIs.
- ETF daily/NAV samples should target `market.etf_daily` and `market.etf_nav`; non-ETF fund/LOF imports should use separate `market.fund_daily` and `market.fund_nav` tables with `asset='fund'`.
- OTC public fund codes such as `110022` returned NAV rows from `get_fund_target` but no daily trading rows from `get_fund_info`; keep that as a separate NAV-only path until its symbol convention is finalized.

## Goal

Use real INSIGHT SDK sample exports to calibrate PostgreSQL + TimescaleDB `CREATE TABLE`
statements before implementing canonical P1 loaders.

## Exported Samples

| Dataset | Symbol | Rows | Result |
|---|---:|---:|---|
| `stock_daily_basic` | `000001.SZ` | 1 | Written |
| `stock_valuation` | `000001.SZ` | 1 | Written |
| `index_component` | `000300.SH` | 300 | Written |
| `etf_daily` from `get_fund_info` | `510300.SH` | 1 | Written |
| `etf_nav` from `get_fund_target` | `510300.SH` | 1 | Written |
| `fund_daily` from `get_fund_info` | `161725.SZ` | 1 | Written |
| `fund_nav` from `get_fund_target` | `161725.SZ` | 1 | Written |
| `etf_basket` | `510300.SH` | 300 | Written |
| `stock_adj_factor` | `000001.SZ` | 0 | Empty for sample day |
| `etf_redemption` | `510300.SH` | 0 | SDK returned `exchange does not exist`; needs parameter or permission confirmation |

## Field Observations

### `stock_daily_basic`

Raw columns:

`htsc_code, name, exchange, trading_day, trading_state, prev_close, open, high, low, close,
backward_adjusted_closing_price, volume, value, turnover_deals, day_change, turnover_rate,
amplitude, avg_price, avg_vol_per_deal, avg_value_per_deal, floating_market_val,
total_market_val`

DDL changes:

- Keep canonical `instrument_id, trading_day, source` primary key.
- Map `prev_close` to `pre_close`, `value` to `amount`, `turnover_deals` to `num_trades`.
- Add `trading_state`, `day_change`, `avg_volume_per_trade`, and `avg_amount_per_trade`.
- Keep `raw_payload` for unmodeled source fields such as `name` and `exchange`.

### `stock_valuation`

Raw columns include source adjusted closes plus valuation ratios:

`close, backward_adjusted_closing_price, forward_adjusted_closing_price, pe, pettm, pb, pc,
pcttm, ps, psttm, avg_price, avg_vol_per_deal, avg_value_per_deal, floating_market_val,
total_market_val`

DDL changes:

- Map `forward_adjusted_closing_price` to `front_adjusted_close`.
- Map `backward_adjusted_closing_price` to `back_adjusted_close`.
- Add `pc_ttm`, `ps_ttm`, `avg_price`, `avg_volume_per_trade`, and `avg_amount_per_trade`.

### `index_component`

Raw columns:

`htsc_code, name, exchange, stock_code, stock_name, stock_exchange, trading_day, weight,
in_date, out_date`

DDL decision:

- Existing `market.index_component` shape is sufficient.
- Names and exchange fields should remain in `raw_payload`; canonical access should join
  `meta.instruments`.

### `etf_daily` from `get_fund_info`

Raw columns:

`htsc_code, name, exchange, delisting_date, trading_day, trading_state, prev_close, open,
high, low, close, discount_rate, backward_adjusted_closing_price, volume, value,
turnover_deals, day_change, unit_nav, discount, discount_ratio, day_change_rate,
turnover_rate, amplitude`

DDL changes:

- Add `delisting_date`, `trading_state`, `discount`, `discount_ratio`, `day_change`,
  and `day_change_rate`.
- Map `prev_close` to `pre_close`, `value` to `amount`, and `turnover_deals` to
  `num_trades`.
- Target table should be `market.etf_daily` for ETF rows. Do not load these rows into
  `market.fund_daily`.

### `etf_nav` from `get_fund_target`

Raw columns:

`htsc_code, name, exchange, end_date, net_unit, total_net_unit, post_net_unit, d1_navgr,
w1_navg, w1_navgr, w4_navg, w4_navgr, w13_navg, w13_navgr, w26_navg, w26_navgr,
w52_navg, w52_navgr, ytdn_avg, ytdn_avgr, y3_navg, y5_navg, sl_navg, navg_vol, beta,
sharper, jensenid, treynorid, r2`

DDL changes:

- Map `net_unit` to `unit_nav`.
- Map `total_net_unit` to `accumulated_nav`.
- Map `post_net_unit` to `adjusted_nav`.
- Add 1d/YTD/since-listing return fields, return rank fields, and `nav_volatility`.
- Map raw `sharper` to canonical `sharpe`.
- Target table should be `market.etf_nav` for ETF rows. Ordinary fund NAV rows should
  use `market.fund_nav`.

### `fund_daily` / `fund_nav`

The `161725.SZ` sample is a non-ETF listed fund/LOF row and uses the same raw column
families as ETF daily/NAV. It should load into `market.fund_daily` and
`market.fund_nav`, not ETF tables.

OTC public fund candidates such as `110022` and `000001` returned NAV rows with
`exchange='DefaultSecurityIDSource'`, but `get_fund_info` returned no daily rows for
the same date. Treat OTC fund NAV import as a later refinement of the fund path rather
than mixing it into ETF semantics.

### `etf_basket`

Raw columns:

`htsc_code, exchange, trading_day, sub_comp_list, pub_date, stock_code, stock_name,
c_type, component_num, unit, is_cash_substitute, cash_substitute_rate, cash_substitute,
sub_replace, red_replace`

DDL changes:

- Map `stock_code` to `component_symbol`.
- Map `component_num` to `quantity`.
- Map `is_cash_substitute` to `cash_substitute_flag`.
- Add `sub_component_list`, `component_type`, `unit`, `cash_substitute_rate`, and
  `subscription_substitute_amount`.

## PostgreSQL Create Statement Decision

The P1 `CREATE TABLE` statements should remain in `sql/init/backend/60_insight.sql`.
That file now includes the sample-backed fields while preserving existing primary keys,
Timescale hypertable declarations, and `raw_payload` fallback columns.

Because local database rebuild is allowed, the schema now separates ETF and ordinary fund
tables:

- `market.etf_daily`: ETF rows from `get_fund_info`.
- `market.etf_nav`: ETF rows from `get_fund_target`.
- `market.fund_daily`: non-ETF listed fund/LOF rows from `get_fund_info`.
- `market.fund_nav`: non-ETF listed fund/LOF rows from `get_fund_target`; OTC fund
  NAV rows need a follow-up symbol convention decision.

Do not create adjusted-price views yet. `stock_valuation` and `stock_adj_factor` must be
cross-checked before choosing the authoritative adjusted-close source.

## Loader Status

Implemented:

- `stock_daily_basic`
- `stock_valuation`
- `index_component`
- `etf_daily`
- `etf_nav`
- `fund_daily`
- `fund_nav`
- `etf_basket`

These datasets can be fetched to `staging.parquet_file` through `fetch-dataset` and
loaded through `load-dataset` after the database schema has the P1 columns.

Remaining:

1. Add `stock_adj_factor` retry samples across a wider date range, because factors are sparse.
2. Confirm `get_etf_redemption` parameters or permissions before making its loader `ready`.
3. Decide whether OTC public fund NAV codes without exchange suffix should be canonicalized
   into `meta.instruments.symbol` as bare codes or source-qualified symbols.
