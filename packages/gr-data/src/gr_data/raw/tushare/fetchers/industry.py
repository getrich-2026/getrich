"""SW2021 一级行业原始快照，按行业与新旧成员分片。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from gr_data.common.parquet import write_parquet
from gr_data.common.paths import RawPaths
from gr_data.raw.tushare.client import TushareClient


@dataclass(frozen=True)
class IndustryRaw:
    """一次完整采集的原件路径与完成时间。"""

    nodes: Path
    members: tuple[Path, ...]
    observed_at: datetime


def fetch_industry(client: TushareClient, paths: RawPaths) -> IndustryRaw:
    """抓取全部一级分类及历史成员；任一分片失败时不返回完整快照。

    使用调用方已配置超时和限流的客户端；本函数不写数据库，异常由任务边界处理。
    每次观察独立保存，不覆盖旧原件。Y/N 都必须请求，避免只得到最新成员。
    """
    observation = uuid4().hex
    try:
        nodes = client.query_all("index_classify", level="L1", src="SW2021")
    except Exception as exc:
        raise RuntimeError("Industry classification request failed") from exc
    if nodes.empty or not {"index_code", "industry_name", "level"} <= set(nodes):
        raise ValueError("Industry classification response is incomplete")
    if nodes["index_code"].duplicated().any():
        raise ValueError("Industry classification response has duplicate nodes")
    node_path = paths.dataset_file("tushare", "index_classify", observation + "/sw2021-l1")
    write_parquet(nodes, node_path)
    members = []
    for code in sorted(nodes["index_code"]):
        for state in ("Y", "N"):
            try:
                frame = client.query_all("index_member_all", l1_code=code, is_new=state)
            except Exception as exc:
                raise RuntimeError(
                    f"Industry membership request failed code={code} state={state}"
                ) from exc
            if not frame.empty and not {"ts_code", "l1_code", "in_date", "out_date"} <= set(frame):
                raise ValueError("Industry membership response is incomplete")
            path = paths.dataset_file(
                "tushare", "index_member_all", f"{observation}/{code}-{state}"
            )
            write_parquet(frame, path)
            members.append(path)
    return IndustryRaw(node_path, tuple(members), datetime.now(timezone.utc))
