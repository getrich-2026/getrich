# 代码归一化

## canonical 约定
- `meta.instruments.symbol`：保留**带交易所后缀的完整代码串**（如 `600000.SH`），避免跨市场重号。
- `exchange`：canonical 交易所码 `XSHG`（上交所）/ `XSHE`（深交所）等。
- `meta.symbol_map`：每个 provider 一行，`(source, source_symbol) → instrument_id`。
  下游/其它 provider 通过它解析 `instrument_id`。

## 各 provider 代码形态
| provider | 原始代码 | 后缀 → exchange |
|---|---|---|
| yinhe | `600000.SH` / `000001.SZ` | SH→XSHG, SZ→XSHE |
| insight | `600000.SH` / `000001.SZ` | 同上 |
| ricequant | `600000.XSHG` / `000001.XSHE` | 后缀已是 canonical |

实现：`ingest/<provider>/symbols.py`（或 adapter 内 `split_*`）。

## 规则
- 不静默改写代码格式。映射规则显式写在代码里。
- 单一来源原则下，每张行情表的 symbol 口径由其唯一 provider 决定；跨源对齐通过 `symbol_map`。
