"""单主机米筐观察存储：文件锁、不可变 Parquet、最后发布 manifest。"""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import asdict
from datetime import date, datetime
from pathlib import Path
from uuid import UUID, uuid4

import pandas as pd

from gr_data.common.parquet import write_parquet
from gr_data.common.paths import RawPaths
from gr_data.common.ricequant_specs import RawIntegrityError, semantic_hash
from gr_data.raw.ricequant.planner import RequestSlice, split_slice


def file_hash(path: Path) -> str:
    """有界读取文件摘要，不加载整份 Parquet 到 Python 字节数组。"""
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def _json_write(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    try:
        temp.write_text(json.dumps(value, sort_keys=True, allow_nan=False), encoding="utf-8")
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


class RqRawStore:
    """一个 dataset/variant 一个 writer；公开读取始终严格验证完整性。"""

    def __init__(self, paths: RawPaths, dataset: str, version: str, variant: str) -> None:
        self.base = paths.ricequant_variant(dataset, version, variant)
        self.root = paths.root.resolve()
        self.dataset, self.version, self.variant = dataset, version, variant
        self._locked = False
        self._next_seq: int | None = None
        self._recoverable: dict[str, dict] = {}

    def _path(self, relative: str) -> Path:
        path = Path(relative)
        if path.is_absolute() or ".." in path.parts:
            raise RawIntegrityError("观察路径必须是根目录内的相对路径")
        resolved = (self.base / path).resolve()
        if not resolved.is_relative_to(self.base.resolve()) or not resolved.is_relative_to(
            self.root
        ):
            raise RawIntegrityError("观察路径含越界符号链接")
        return self.base / path

    @contextmanager
    def writer(self) -> Iterator[RqRawStore]:
        """整个单元下载与发布期间持锁；竞争时立即失败，不并行修改观察序号。"""
        self._path(".").mkdir(parents=True, exist_ok=True)
        with self._path("_writer.lock").open("a") as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise RawIntegrityError("该米筐 variant 已有采集任务") from None
            self._locked = True
            self._next_seq = None
            self._recoverable = {}
            try:
                yield self
            finally:
                self._locked = False
                fcntl.flock(lock, fcntl.LOCK_UN)

    def _read_json(self, path: Path) -> dict:
        self._path(str(path.relative_to(self.base)))
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            raise RawIntegrityError("米筐观察元数据损坏") from None
        if not isinstance(value, dict):
            raise RawIntegrityError("米筐观察元数据必须为对象")
        return value

    def _validate(self, manifest: dict) -> RequestSlice:
        try:
            request = RequestSlice(**manifest["request"])
            if not isinstance(manifest["observation_id"], str):
                raise ValueError
            UUID(manifest["observation_id"])
            if (
                request.dataset != self.dataset
                or request.variant_id != self.variant
                or request.contract_version != self.version
                or manifest["request_id"] != request.request_id
                or semantic_hash(manifest["evidence"]) != request.evidence_hash
                or manifest["format_version"] != 1
                or type(manifest["observation_seq"]) is not int
                or manifest["observation_seq"] < 1
            ):
                raise ValueError
        except (KeyError, TypeError, ValueError):
            raise RawIntegrityError("米筐观察身份或请求摘要不一致") from None
        return request

    def _observation_path(self, plan: dict, filename: str) -> Path:
        request = self._validate(plan)
        return self._path(f"observations/{request.month}/{plan['observation_id']}/{filename}")

    def _load_recovery(self) -> None:
        """每次持锁只扫一遍元数据，避免逐日抓取产生二次方磁盘扫描。"""
        seqs: set[int] = set()
        for folder in self.base.glob("observations/*/*"):
            plan_path, manifest_path = folder / "plan.json", folder / "manifest.json"
            if not plan_path.exists() and not manifest_path.exists():
                continue
            plan = self._read_json(plan_path if plan_path.exists() else manifest_path)
            request = self._validate(plan)
            if folder.name != plan["observation_id"] or folder.parent.name != request.month:
                raise RawIntegrityError("观察计划目录与身份不一致")
            if plan["observation_seq"] in seqs:
                raise RawIntegrityError("米筐观察计划序号重复")
            seqs.add(plan["observation_seq"])
            status = self._read_json(manifest_path)["status"] if manifest_path.exists() else None
            orphan = self._path(
                f"{request.month}/{plan['observation_id']}/{request.request_id}.parquet"
            )
            if status in {None, "failed", "blocked"} and not orphan.exists():
                self._recoverable[request.request_id] = plan
        self._next_seq = max(seqs, default=0) + 1

    def begin(
        self, request: RequestSlice, *, sdk_version: str, evidence: dict, minimum_seq: int = 0
    ) -> dict:
        """恢复未结束的同请求计划；新请求分配新观察，序号从磁盘恢复。"""
        if not self._locked:
            raise RawIntegrityError("写观察前必须持锁")
        if self._next_seq is None:
            self._load_recovery()
        assert self._next_seq is not None
        previous = self._recoverable.get(request.request_id)
        if previous is not None and previous["observation_seq"] >= minimum_seq:
            return previous
        plan = {
            "format_version": 1,
            "observation_id": str(uuid4()),
            "observation_seq": self._next_seq,
            "request": asdict(request),
            "request_id": request.request_id,
            "sdk_version": sdk_version,
            "evidence": evidence,
        }
        self._validate(plan)
        _json_write(self._observation_path(plan, "plan.json"), plan)
        self._next_seq += 1
        self._recoverable[request.request_id] = plan
        return plan

    def publish(
        self,
        plan: dict,
        frame: pd.DataFrame | None,
        *,
        status: str,
        observed_at: datetime,
        detail: str = "",
        children: tuple[RequestSlice, ...] = (),
    ) -> dict:
        """每次观察只发布一个完整单元；成功文件和已完成 manifest 不可覆盖。"""
        if not self._locked:
            raise RawIntegrityError("发布观察前必须持锁")
        request = self._validate(plan)
        if observed_at.tzinfo is None or status not in {
            "complete",
            "valid_empty",
            "not_applicable",
            "blocked",
            "failed",
            "split",
        }:
            raise RawIntegrityError("非法观察状态或无时区时间")
        manifest_path = self._observation_path(plan, "manifest.json")
        if manifest_path.exists():
            old = self._read_json(manifest_path)
            if old["status"] in {"complete", "valid_empty", "not_applicable", "split"}:
                raise RawIntegrityError("不可覆盖已完成观察")
        relative = f"{request.month}/{plan['observation_id']}/{request.request_id}.parquet"
        path = self._path(relative)
        manifest = dict(
            plan,
            status=status,
            observed_at=observed_at.isoformat(),
            detail=detail,
            path=None,
            file_hash=None,
            rows=0,
            schema_fingerprint=None,
            children=[asdict(child) for child in children],
            source_metadata=frame.attrs.get("source_metadata", {}) if frame is not None else {},
        )
        if status == "valid_empty" and (
            request.dataset != "rq_index_components"
            or not manifest["source_metadata"].get("create_tm")
        ):
            raise RawIntegrityError("空成分观察必须保留 create_tm 证据")
        if status == "not_applicable" and not request.not_applicable:
            raise RawIntegrityError("该请求不能标为不适用")
        if status == "split" and (not children or children != split_slice(request)):
            raise RawIntegrityError("分片子计划没有精确覆盖父请求")
        if frame is not None and not frame.empty:
            if status != "complete" or path.exists():
                raise RawIntegrityError("观察文件已存在或状态不允许发布数据")
            write_parquet(frame, path)
            manifest.update(
                path=relative,
                file_hash=file_hash(path),
                rows=len(frame),
                schema_fingerprint=semantic_hash(
                    [(str(k), str(v)) for k, v in frame.dtypes.items()]
                ),
            )
        elif status == "complete":
            raise RawIntegrityError("空响应不能标为 complete")
        _json_write(manifest_path, manifest)
        if status in {"complete", "valid_empty", "not_applicable", "split"}:
            self._recoverable.pop(request.request_id, None)
        return manifest

    def read(self, manifest: dict) -> pd.DataFrame | None:
        """校验 manifest 指向的文件；孤立文件不会通过本入口被发现。"""
        request = self._validate(manifest)
        try:
            observed = datetime.fromisoformat(manifest["observed_at"])
            if observed.tzinfo is None or observed.utcoffset() is None:
                raise ValueError
            if manifest["status"] == "valid_empty":
                if request.dataset != "rq_index_components":
                    raise ValueError
                created = manifest["source_metadata"]["create_tm"]
                datetime.fromisoformat(created)
            if manifest["status"] == "not_applicable" and not request.not_applicable:
                raise ValueError
            if manifest["status"] == "split":
                children = manifest["children"]
                expected = [asdict(child) for child in split_slice(request)]
                if not children or semantic_hash(children) != semantic_hash(expected):
                    raise ValueError
        except (ValueError, KeyError, TypeError):
            raise RawIntegrityError("观察缺少合法的时间或空快照证据") from None
        relative = manifest.get("path")
        if relative is None:
            if manifest.get("rows") != 0 or manifest["status"] not in {
                "valid_empty",
                "not_applicable",
                "failed",
                "blocked",
                "split",
            }:
                raise RawIntegrityError("观察缺少数据文件")
            return None
        expected = f"{request.month}/{manifest['observation_id']}/{request.request_id}.parquet"
        if relative != expected or manifest["status"] != "complete":
            raise RawIntegrityError("观察文件路径与请求不一致")
        path = self._path(relative)
        try:
            if file_hash(path) != manifest["file_hash"]:
                raise RawIntegrityError("米筐 Parquet hash 不匹配")
            frame = pd.read_parquet(path)
        except (OSError, ValueError):
            raise RawIntegrityError("米筐 Parquet 不可读") from None
        fingerprint = semantic_hash([(str(k), str(v)) for k, v in frame.dtypes.items()])
        if len(frame) != manifest["rows"] or fingerprint != manifest["schema_fingerprint"]:
            raise RawIntegrityError("米筐行数或 schema 不匹配")
        return frame

    def completed_requests(self) -> set[str]:
        """逐片校验已完成覆盖；拆分父片只有所有子片完成后才能推进。"""
        return self.progress()[0]

    def progress(
        self, *, minimum_seq: int = 0
    ) -> tuple[set[str], dict[str, tuple[RequestSlice, ...]]]:
        """读取指定观察轮次之后的完成片及拆分树；不拿旧观察代替本轮结果。"""
        completed: set[str] = set()
        splits: dict[str, tuple[RequestSlice, ...]] = {}
        for manifest in self.manifests():
            if manifest["observation_seq"] < minimum_seq:
                continue
            self.read(manifest)
            if manifest["status"] in {"complete", "valid_empty", "not_applicable"}:
                completed.add(manifest["request_id"])
            elif manifest["status"] == "split":
                splits[manifest["request_id"]] = tuple(
                    RequestSlice(**child) for child in manifest["children"]
                )
        while True:
            resolved = {
                parent
                for parent, children in splits.items()
                if all(child.request_id in completed for child in children)
            }
            if resolved <= completed:
                return completed, splits
            completed.update(resolved)

    def _round_path(self, scope: list[RequestSlice]) -> Path:
        return self._path(f"rounds/{semantic_hash([r.request_id for r in scope])}.json")

    def start_round(
        self, scope: list[RequestSlice], requests: list[RequestSlice], completed: set[str]
    ) -> tuple[list[tuple[RequestSlice, bool]], int]:
        """先持久化本轮计划及序号下界；同范围恢复沿用原计划，支持 init 转 update。"""
        if not self._locked:
            raise RawIntegrityError("写采集轮次前必须持锁")
        path = self._round_path(scope)
        if path.exists():
            state = self._read_json(path)
            try:
                minimum_seq = state["minimum_seq"]
                pending = [
                    (RequestSlice(**item["request"]), item["resume"]) for item in state["requests"]
                ]
                ids = [request.request_id for request, _ in pending]
                if (
                    state["format_version"] != 1
                    or type(minimum_seq) is not int
                    or minimum_seq < 1
                    or len(ids) != len(set(ids))
                    or not set(ids) <= {r.request_id for r in scope}
                    or any(type(resume) is not bool for _, resume in pending)
                ):
                    raise ValueError
            except (KeyError, TypeError, ValueError):
                raise RawIntegrityError("米筐采集轮次计划损坏或与当前范围不一致") from None
            return pending, minimum_seq
        if self._next_seq is None:
            self._load_recovery()
        assert self._next_seq is not None
        # 首次启用或旧版本已有缺口时，先补缺片，避免回扫耗尽额度。
        ordered = sorted(requests, key=lambda r: r.request_id in completed)
        pending = [(request, request.request_id not in completed) for request in ordered]
        _json_write(
            path,
            {
                "format_version": 1,
                "minimum_seq": self._next_seq,
                "requests": [
                    {"request": asdict(request), "resume": resume} for request, resume in pending
                ],
            },
        )
        return pending, self._next_seq

    def finish_round(self, scope: list[RequestSlice]) -> None:
        """仅在全部计划完成后清理运行检查点；不可变观察继续保留。"""
        if not self._locked:
            raise RawIntegrityError("结束采集轮次前必须持锁")
        self._round_path(scope).unlink()

    def manifests(self, months: tuple[str, ...] | None = None) -> list[dict]:
        """先筛 manifest 月份，再读文件；返回观察顺序，拒绝重复序号。"""
        found = []
        if months is not None:
            for month in months:
                try:
                    if date.fromisoformat(month + "-01").strftime("%Y-%m") != month:
                        raise ValueError
                except (ValueError, TypeError):
                    raise RawIntegrityError("非法观察月份筛选") from None
        roots = (
            [self._path(f"observations/{m}") for m in dict.fromkeys(months)]
            if months is not None
            else [self._path("observations")]
        )
        candidates = (
            p
            for root in roots
            for p in root.glob("*/manifest.json" if months is not None else "*/*/manifest.json")
        )
        for path in candidates:
            manifest = self._read_json(path)
            request = self._validate(manifest)
            if (
                path.parent.name != manifest["observation_id"]
                or path.parent.parent.name != request.month
            ):
                raise RawIntegrityError("观察目录与 ID 不一致")
            if months is None or request.month in months:
                found.append(manifest)
        seqs = [m["observation_seq"] for m in found]
        if len(seqs) != len(set(seqs)):
            raise RawIntegrityError("米筐观察序号重复")
        return sorted(found, key=lambda m: m["observation_seq"])
