"""动态风险观察的不可变登记、采集检查点与逻辑整包入库收据。"""

from __future__ import annotations

import re
import subprocess
import uuid
from datetime import date, datetime
from functools import lru_cache
from pathlib import Path
from typing import Any

import psycopg
from psycopg.pq import TransactionStatus
from psycopg.types.json import Jsonb

from gr_data.common.ownership import OwnershipManager
from gr_data.common.ricequant_specs import ContractViolationError, semantic_hash
from gr_data.config.ricequant_risk import RiskOptions


TARGET = "factor.risk_bundle"
_VERSION_PATHS = ("packages/gr-data/src/gr_data", "packages/gr-db/src/gr_db/ddl")
_GIT_TIMEOUT_SECONDS = 5
_PROVIDER = "ricequant"
_DATASET = "rq_risk_model"
_RECEIPT_COLUMNS = (
    "receipt_id, target, variant_id, manifest_hash, importer_version, observation_id, "
    "trading_day, rows_written, quality, committed_at"
)


def _git(directory: Path, *args: str) -> str:
    """只读 Git 查询；错误只给类型化固定摘要，不回显路径、配置或 stderr。"""
    try:
        result = subprocess.run(
            [
                "git",
                "--no-pager",
                "--no-optional-locks",
                "-c",
                "core.fsmonitor=false",
                "-C",
                str(directory),
                *args,
            ],
            capture_output=True,
            timeout=_GIT_TIMEOUT_SECONDS,
            check=True,
        )
        return result.stdout.decode("utf-8").strip()
    except (OSError, subprocess.SubprocessError, UnicodeError) as exc:
        raise ContractViolationError(
            "RiceQuant importer version requires an accessible Git checkout"
        ) from exc


@lru_cache(maxsize=1)
def _checkout_root() -> Path:
    module = Path(__file__).resolve()
    root = Path(_git(module.parent, "rev-parse", "--show-toplevel"))
    if module != root / _VERSION_PATHS[0] / "db/risk_receipts.py":
        raise ContractViolationError(
            "RiceQuant importer source is outside its expected Git checkout"
        )
    return root


def _latest_importer_commit(root: Path) -> str:
    commit = _git(root, "log", "-1", "--format=%H", "--", *_VERSION_PATHS)
    if re.fullmatch(r"(?:[0-9a-f]{40}|[0-9a-f]{64})", commit) is None:
        raise ContractViolationError(
            "RiceQuant importer source has no complete Git commit identity"
        )
    return commit


@lru_cache(maxsize=1)
def _bound_importer_commit(root: Path) -> str:
    """绑定本进程首次识别的代码身份，不能随磁盘提交切换已加载的内存代码。"""
    return _latest_importer_commit(root)


def get_importer_version(*, require_clean: bool = False) -> str:
    """返回最近影响导入源码或 DDL 的完整提交号；模块导入时不执行 Git。

    每次重查源码提交并与本进程首次绑定值对比，变化即要求重启；文档提交不影响。
    生产预检每次检查受保护源码路径，
    拒绝 tracked 修改和未忽略的 untracked 文件，不用环境变量覆盖版本或放行。
    非 checkout 安装、Git 缺失、无源码提交均拒绝，避免伪造可追溯身份。
    """
    root = _checkout_root()
    if require_clean and _git(
        root, "status", "--porcelain=v1", "--untracked-files=all", "--", *_VERSION_PATHS
    ):
        raise ContractViolationError(
            "RiceQuant production requires committed importer source and DDL"
        )
    current = _latest_importer_commit(root)
    bound = _bound_importer_commit(root)
    if current != bound:
        raise ContractViolationError(
            "RiceQuant importer source commit changed; restart the process"
        )
    return bound


def _idle(conn: psycopg.Connection) -> None:
    if conn.info.transaction_status != TransactionStatus.IDLE:
        raise ValueError("RiceQuant capture registration requires an idle connection")


def _claim_evidence_table(conn: psycopg.Connection, target: str, channel: str) -> None:
    """在调用方事务中锁定归属并登记风险证据表，拒绝其他 provider 串写。

    channel 须与同批业务表的登记一致，否则 claim 的 UPSERT 会来回改写归属通道。
    """
    with conn.cursor() as cur:
        cur.execute("LOCK TABLE ops.table_ownership IN SHARE ROW EXCLUSIVE MODE")
    OwnershipManager(conn).claim(target, _PROVIDER, channel=channel, force=False)


def _register_variant(conn: psycopg.Connection, options: RiskOptions, channel: str) -> None:
    if options.contract_version != "v2" or options.purpose not in {"validation", "production"}:
        raise ContractViolationError("RiceQuant receipts require an explicit dynamic purpose")
    row = (options.variant_id, _PROVIDER, _DATASET, options.purpose, options.identity)
    with conn.cursor() as cur:
        cur.execute(
            "SELECT file_name FROM ops.schema_migrations WHERE file_name=%s",
            ("049_risk_import_receipts.sql",),
        )
        if cur.fetchone() is None:
            raise ContractViolationError(
                "RiceQuant capture requires migration 049_risk_import_receipts.sql"
            )
        _claim_evidence_table(conn, "factor.dataset_variant", channel)
        cur.execute(
            "INSERT INTO factor.dataset_variant (variant_id, provider, "
            "dataset_name, purpose, identity) "
            "VALUES (%s,%s,%s,%s,%s) ON CONFLICT (variant_id) DO NOTHING",
            (*row[:4], Jsonb(row[4])),
        )
        cur.execute(
            "SELECT variant_id, provider, dataset_name, purpose, identity "
            "FROM factor.dataset_variant WHERE variant_id=%s",
            (options.variant_id,),
        )
        stored = cur.fetchone()
    if stored is None or tuple(stored) != row:
        raise ContractViolationError("Immutable RiceQuant dataset variant conflict")


def prepare_capture(
    conn: psycopg.Connection, options: RiskOptions, *, channel: str = "ingest"
) -> None:
    """在 SDK 调用前检查收据迁移并登记不可变用途；拥有且提交自己的事务。"""
    _idle(conn)
    get_importer_version(require_clean=options.purpose == "production")
    with conn.transaction():
        _register_variant(conn, options, channel)
        with conn.cursor() as cur:
            cur.execute("SELECT receipt_id FROM factor.import_receipt LIMIT 0")
            cur.execute("SELECT run_id FROM factor.model_run_binding LIMIT 0")
            cur.execute("SELECT capture_manifest_hash FROM factor.import_checkpoint LIMIT 0")


def _identity(options: RiskOptions, manifest: dict[str, Any]) -> tuple[str, date, str, str]:
    if (
        manifest.get("variant_id") != options.variant_id
        or manifest.get("identity") != options.identity
    ):
        raise ContractViolationError("RiceQuant receipt identity differs from configuration")
    if manifest.get("purpose") != options.purpose:
        raise ContractViolationError("RiceQuant receipt purpose differs from configuration")
    day = date.fromisoformat(manifest["day"])
    observation = manifest["observation_id"]
    manifest_hash = semantic_hash(manifest)
    return f"{options.variant_id}/{day}/{observation}", day, observation, manifest_hash


def record_capture(
    conn: psycopg.Connection,
    options: RiskOptions,
    manifest: dict[str, Any],
    *,
    channel: str = "ingest",
) -> None:
    """已校验 raw 的采集登记；独立提交，后续业务事务失败不撤销采集证据。

    captured_at 保留实际 raw observed_at；按每个观察登记，不表示连续日期水位。
    重放只检查固定身份，不把已有 imported 检查点退回 captured。
    """
    _idle(conn)
    get_importer_version(require_clean=options.purpose == "production")
    partition, day, observation, digest = _identity(options, manifest)
    captured_at = datetime.fromisoformat(manifest["observed_at"])
    if captured_at.tzinfo is None or captured_at.utcoffset() is None:
        raise ContractViolationError("RiceQuant capture time must be timezone-aware")
    frozen = {
        "manifest_hash": digest,
        "purpose": options.purpose,
        "contract": options.identity["contract"],
    }
    row = (options.variant_id, observation, day, digest, captured_at, frozen)
    with conn.transaction():
        _register_variant(conn, options, channel)
        _claim_evidence_table(conn, "factor.import_checkpoint", channel)
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO factor.import_checkpoint "
                "(provider,dataset_name,partition_key,variant_id,observation_id,trading_day,"
                "capture_manifest_hash,captured_at,state) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s) "
                "ON CONFLICT (provider,dataset_name,partition_key) DO NOTHING",
                (_PROVIDER, _DATASET, partition, *row[:5], Jsonb(frozen)),
            )
            cur.execute(
                "SELECT variant_id,observation_id,trading_day,"
                "capture_manifest_hash,captured_at,state "
                "FROM factor.import_checkpoint WHERE provider=%s AND "
                "dataset_name=%s AND partition_key=%s "
                "FOR UPDATE",
                (_PROVIDER, _DATASET, partition),
            )
            stored = cur.fetchone()
        if stored is None or tuple(stored) != row:
            raise ContractViolationError("Immutable RiceQuant capture manifest conflict")


def probe_receipt(
    conn: psycopg.Connection, options: RiskOptions, manifest: dict[str, Any]
) -> dict[str, Any] | None:
    """调用者事务内读取相同 importer 的唯一整包收据；有收据时禁止重写业务数据。"""
    _, day, observation, digest = _identity(options, manifest)
    importer_version = get_importer_version()
    with conn.cursor() as cur:
        cur.execute(
            f"SELECT {_RECEIPT_COLUMNS} FROM factor.import_receipt "
            "WHERE target=%s AND manifest_hash=%s AND importer_version=%s",
            (TARGET, digest, importer_version),
        )
        stored = cur.fetchone()
    if stored is None:
        return None
    row = dict(zip((part.strip() for part in _RECEIPT_COLUMNS.split(",")), stored, strict=True))
    if (row["variant_id"], row["observation_id"], row["trading_day"]) != (
        options.variant_id,
        observation,
        day,
    ):
        raise ContractViolationError("Immutable RiceQuant receipt identity conflict")
    return row


def commit_receipt(
    conn: psycopg.Connection,
    options: RiskOptions,
    manifest: dict[str, Any],
    run_id: uuid.UUID,
    rows_written: int,
    quality: dict[str, Any],
    *,
    channel: str = "ingest",
) -> dict[str, Any]:
    """五件套、覆盖与 ETL 所在事务内绑定收据并推进当前观察的 DB 检查点。

    不提交事务；调用者任一步失败时，业务、收据、绑定、入库检查点一起回滚。
    committed_at 是收据在事务内的写入时刻，不是数据库实际 COMMIT 时刻。
    """
    if conn.info.transaction_status != TransactionStatus.INTRANS:
        raise ValueError("RiceQuant receipt commit requires an active transaction")
    partition, day, observation, digest = _identity(options, manifest)
    importer_version = get_importer_version()
    receipt_id = uuid.uuid5(uuid.NAMESPACE_URL, f"{TARGET}:{digest}:{importer_version}")
    _claim_evidence_table(conn, "factor.import_receipt", channel)
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO factor.import_receipt "
            "(receipt_id,target,variant_id,manifest_hash,importer_version,"
            "observation_id,trading_day,rows_written,quality) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s) "
            "ON CONFLICT (target,manifest_hash,importer_version) DO NOTHING",
            (
                receipt_id,
                TARGET,
                options.variant_id,
                digest,
                importer_version,
                observation,
                day,
                rows_written,
                Jsonb(quality),
            ),
        )
    receipt = probe_receipt(conn, options, manifest)
    if (
        receipt is None
        or receipt["receipt_id"] != receipt_id
        or receipt["rows_written"] != rows_written
        or receipt["quality"] != quality
    ):
        raise ContractViolationError("Immutable RiceQuant import receipt conflict")
    binding = (run_id, receipt_id, options.variant_id, observation, day)
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO factor.model_run_binding "
            "(run_id,receipt_id,variant_id,observation_id,trading_day) "
            "VALUES (%s,%s,%s,%s,%s) ON CONFLICT (run_id) DO NOTHING",
            binding,
        )
        cur.execute(
            "SELECT run_id,receipt_id,variant_id,observation_id,trading_day "
            "FROM factor.model_run_binding "
            "WHERE run_id=%s",
            (run_id,),
        )
        stored = cur.fetchone()
        if stored is None or tuple(stored) != binding:
            raise ContractViolationError("Immutable RiceQuant model run binding conflict")
        cur.execute(
            "UPDATE factor.import_checkpoint SET "
            "import_receipt_id=%s,imported_at=%s,watermark_date=%s,updated_at=clock_timestamp() "
            "WHERE provider=%s AND dataset_name=%s AND partition_key=%s "
            "AND import_receipt_id IS NULL",
            (receipt_id, receipt["committed_at"], day, _PROVIDER, _DATASET, partition),
        )
        cur.execute(
            "SELECT import_receipt_id,imported_at,watermark_date FROM factor.import_checkpoint "
            "WHERE provider=%s AND dataset_name=%s AND partition_key=%s",
            (_PROVIDER, _DATASET, partition),
        )
        checkpoint = cur.fetchone()
        if checkpoint is None or tuple(checkpoint) != (receipt_id, receipt["committed_at"], day):
            raise ContractViolationError("RiceQuant imported checkpoint conflict")
    return receipt


def verify_committed_receipt(
    conn: psycopg.Connection,
    options: RiskOptions,
    manifest: dict[str, Any],
    run_id: uuid.UUID,
    receipt: dict[str, Any],
) -> None:
    """重放跳过业务前确认 run 绑定和当前观察的 DB 检查点都已完整登记。"""
    partition, day, observation, _ = _identity(options, manifest)
    expected = (run_id, receipt["receipt_id"], options.variant_id, observation, day)
    with conn.cursor() as cur:
        cur.execute(
            "SELECT run_id,receipt_id,variant_id,observation_id,trading_day "
            "FROM factor.model_run_binding WHERE run_id=%s",
            (run_id,),
        )
        binding = cur.fetchone()
        cur.execute(
            "SELECT import_receipt_id,imported_at,watermark_date FROM factor.import_checkpoint "
            "WHERE provider=%s AND dataset_name=%s AND partition_key=%s",
            (_PROVIDER, _DATASET, partition),
        )
        checkpoint = cur.fetchone()
    if binding is None or tuple(binding) != expected:
        raise ContractViolationError("RiceQuant receipt has no matching model run binding")
    if checkpoint is None or tuple(checkpoint) != (
        receipt["receipt_id"],
        receipt["committed_at"],
        day,
    ):
        raise ContractViolationError("RiceQuant receipt has no matching imported checkpoint")
