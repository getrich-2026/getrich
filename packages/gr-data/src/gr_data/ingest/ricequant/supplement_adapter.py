"""离线发现米筐观察；仅消费已发布 manifest，不调用 SDK 或建立数据库连接。"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass

import pandas as pd

from gr_data.common.paths import RawPaths
from gr_data.common.ricequant_specs import RawIntegrityError, semantic_hash
from gr_data.config.ricequant import DatasetOptions
from gr_data.raw.ricequant.planner import RequestSlice
from gr_data.raw.ricequant.shapes import decode_response
from gr_data.raw.ricequant.store import RqRawStore


@dataclass(frozen=True)
class RawPartition:
    manifest: dict
    frame: pd.DataFrame | None
    manifest_hash: str


def iter_observations(
    paths: RawPaths,
    options: DatasetOptions,
    *,
    months: tuple[str, ...] | None = None,
) -> Iterator[RawPartition]:
    """逐片验证哈希和当前准入证据；新 writer 未实现前仅供离线转换验证。"""
    store = RqRawStore(paths, options.name, options.contract_version, options.variant_id)
    for manifest in store.manifests(months):
        if manifest["status"] in {"failed", "blocked", "not_applicable", "split"}:
            continue
        if semantic_hash(manifest["evidence"]) != options.evidence_hash:
            raise RawIntegrityError("观察准入证据与当前已核实版本不一致")
        frame = store.read(manifest)
        request = RequestSlice(**manifest["request"])
        if frame is not None:
            # 哈希只证明文件没变化；离线消费仍需重验行键和返回契约。
            if request.dataset == "rq_index_daily":
                decode_response(request, frame)
            else:
                required = {"index_code", "query_date", "member_source_symbol"}
                if not required <= set(frame.columns):
                    raise RawIntegrityError("快照缺少源键")
                if (
                    not frame["index_code"].eq(request.codes[0]).all()
                    or not frame["query_date"].eq(request.start_date).all()
                ):
                    raise RawIntegrityError("快照内容与请求范围不一致")
                if request.dataset == "rq_index_components":
                    if "create_tm" not in frame or frame["create_tm"].nunique(dropna=False) != 1:
                        raise RawIntegrityError("成分快照源时间不一致")
                    decode_response(
                        request,
                        (frame["member_source_symbol"].tolist(), frame["create_tm"].iloc[0]),
                    )
                else:
                    if "weight" not in frame:
                        raise RawIntegrityError("权重快照缺 weight")
                    decode_response(
                        request,
                        pd.Series(frame["weight"].to_numpy(), index=frame["member_source_symbol"]),
                    )
        yield RawPartition(manifest, frame, semantic_hash(manifest))
