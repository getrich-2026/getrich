"""生成 GetRich PostgreSQL、ClickHouse 与 raw 数据字典。"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from .introspect import introspect_clickhouse, introspect_postgres
from .model import Dictionary
from .provenance import discover_datasets, enrich_provenance, fetch_ownership
from .render import render_html


def build_dictionary(
    postgres_conn: Any | None = None,
    clickhouse_client: Any | None = None,
) -> Dictionary:
    """从可用数据库连接构建数据字典。

    至少提供一个连接；未提供的一层仍会在产物中保留 raw 数据集清单。

    Time Complexity: O(t + c + r + f)，由数据库 catalog、注册表和 raw 文件规模决定。
    Space Complexity: O(t + c + r)。
    """
    if postgres_conn is None:
        schemas = ()
        findings = ()
    else:
        schemas = introspect_postgres(postgres_conn)
        ownership = fetch_ownership(postgres_conn)
        schemas, findings = enrich_provenance(schemas, ownership)
    clickhouse_tables = (
        introspect_clickhouse(clickhouse_client) if clickhouse_client is not None else ()
    )
    return Dictionary(
        schemas=schemas,
        clickhouse_tables=clickhouse_tables,
        datasets=discover_datasets(),
        findings=findings,
        generated_at=datetime.now(timezone.utc).isoformat(),
    )


__all__ = ["build_dictionary", "render_html"]
