"""已批准历史身份规则的复核、逐月准入与 raw 回补；绝不调用业务 ingest。"""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import logging
import os
import shutil
import subprocess
import time
import traceback
from datetime import date, datetime, timezone
from functools import partial
from pathlib import Path
from typing import Any
from uuid import uuid4
from zoneinfo import ZoneInfo

import pandas as pd
import psycopg
import yaml
from gr_data.common.paths import RawPaths
from gr_data.common.ricequant_delayed_gate import (
    APPROVED_POLICY_SHA256,
    VerifiedRiskObservation,
    VerifiedTradingCalendar,
    evaluate_delayed_day,
    monthly_summary,
)
from gr_data.common.ricequant_specs import BudgetDeferredError, semantic_hash
from gr_data.common.ricequant_symbol_intervals import (
    APPROVED_HISTORY_SYMBOL_RULES_VERSION,
    symbol_rule_evidence,
    symbol_rule_hash,
)
from gr_data.common.ricequant_universe import build_universe_provider
from gr_data.config.ricequant import RicequantImportOptions
from gr_data.config.ricequant_risk import RiskOptions, parse_risk_options
from gr_data.config.settings import load_postgres, make_pg_dsn
from gr_data.db.postgres.risk_receipts import get_importer_version, prepare_capture, record_capture
from gr_data.raw.base import RawContext
from gr_data.raw.ricequant.client import RqdatacClient
from gr_data.raw.ricequant.risk_dynamic import validate_universe
from gr_data.raw.ricequant.risk_shapes import STYLE_FACTORS
from gr_data.raw.ricequant.riskmodel import _quota_snapshot, run_risk_raw
from gr_tools.config import LoggingConfig, load_environment, setup_logging


log = logging.getLogger(__name__)
MODELS = ("v2", "v2trd", "v1")
STARTS = {"v1": "2010-01-04", "v2": "2011-04-28", "v2trd": "2011-04-28"}
RESERVE = 0.03
DAY_BUFFER = 32 * 1024**2


def digest(path: Path) -> str:
    """文件字节哈希。"""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save(path: Path, value: object) -> None:
    """只写显式证据目录，原子发布，不保存环境凭据。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp-" + uuid4().hex)
    try:
        temporary.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2))
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def monthly_days(days: list[str]) -> list[str]:
    """2011-04 使用获批候选日，其后每月首个实际交易日，共153个月。"""
    selected: dict[str, str] = {}
    for day in days:
        if "2011-04-28" <= day <= "2023-12-31":
            selected.setdefault(day[:7], day)
    if len(selected) != 153 or selected.get("2011-04") != "2011-04-28":
        raise ValueError("Monthly calendar does not cover the approved 153 months")
    return list(selected.values())


def quota_reached(snapshot: dict[str, Any]) -> bool:
    """日启动缓冲另留32MiB；原raw在每请求前仍严格保留3%。"""
    limit, used = snapshot["bytes_limit"], snapshot["bytes_used"]
    return bool(limit and limit - used <= limit * RESERVE + DAY_BUFFER)


def verify_seven_targets(rows: list[dict[str, Any]]) -> None:
    """七项必须是明确目标集合，重复记录不能替代漏掉的模型日。"""
    expected = {("v1", "2010-01-04")} | {
        (model, day) for model in MODELS for day in ("2014-01-06", "2017-01-04")
    }
    if len(rows) != 7 or {(row["model"], row["day"]) for row in rows} != expected:
        raise ValueError("Identity recheck must contain the exact seven unique targets")


def axis_changes(rows: list[dict[str, Any]], expected_industry: str) -> list[dict[str, Any]]:
    """逐模型检查完整因子集合和已验证行业集合；变化不自动沿用variant。"""
    previous: dict[str, dict[str, Any]] = {}
    changes = []
    for row in sorted(rows, key=lambda item: (item["model"], item["day"])):
        prior = previous.get(row["model"])
        if row["industry_axis_sha256"] != expected_industry or (
            prior is not None and prior["factor_set_sha256"] != row["factor_set_sha256"]
        ):
            changes.append({"previous": prior, "current": row})
        previous[row["model"]] = row
    return changes


def compare_piece(
    old: pd.DataFrame,
    new: pd.DataFrame,
    old_codes: dict[str, str],
    new_codes: dict[str, str],
    piece: str,
) -> dict[str, Any]:
    """逐接口按实际返回完整代码比较原单位；旧未观察者不补值。"""
    if piece in {"factor_return", "covariance"}:
        if set(old.index) != set(new.index) or set(old.columns) != set(new.columns):
            raise ValueError("Global factor axes changed between observations")
        equal = old.sort_index().sort_index(axis=1).equals(new.sort_index().sort_index(axis=1))
        result = {"common_values_equal": equal, "compared_values": old.size}
    else:
        left, right = old.copy(), new.copy()
        if piece == "exposure":
            left.index = [old_codes[code] for code in left.index]
            right.index = [new_codes[code] for code in right.index]
            if set(left.columns) != set(right.columns):
                raise ValueError("Exposure factor axes changed")
            common = sorted(set(left.index) & set(right.index))
            equal = left.loc[common].sort_index(axis=1).equals(right.loc[common].sort_index(axis=1))
            new_only = sorted(set(right.index) - set(left.index))
            old_only = sorted(set(left.index) - set(right.index))
            size = len(common) * len(left.columns)
        else:
            left.columns = [old_codes[code] for code in left.columns]
            right.columns = [new_codes[code] for code in right.columns]
            if set(left.index) != set(right.index):
                raise ValueError("Specific response date axis changed")
            common = sorted(set(left.columns) & set(right.columns))
            equal = left.loc[:, common].sort_index().equals(right.loc[:, common].sort_index())
            new_only = sorted(set(right.columns) - set(left.columns))
            old_only = sorted(set(left.columns) - set(right.columns))
            size = len(common) * len(left.index)
        result = {
            "common_values_equal": equal,
            "compared_values": size,
            "old_not_observed_now_returned": new_only,
            "old_returned_now_absent": old_only,
        }
        if old_only:
            raise ValueError("Previously returned securities disappeared")
    if not result["common_values_equal"]:
        raise ValueError("Common raw numeric values changed")
    return result


def verify_raw_evidence(evidence: dict[str, Any]) -> dict[str, Any]:
    """已验收恢复时核所有原文件字节；载荷不变才能复用此前严格验收。"""
    path = Path(evidence["path"])
    if digest(path) != evidence["file_sha256"]:
        raise ValueError("Accepted manifest changed")
    manifest = json.loads(path.read_text())
    if semantic_hash(manifest) != evidence["manifest_sha256"]:
        raise ValueError("Accepted manifest semantic hash changed")
    files = {piece + ".parquet": value for piece, value in manifest["files"].items()}
    files.update({row["file"]: row["sha256"] for row in manifest["requests"] if row.get("file")})
    for filename, expected in files.items():
        target = (path.parent / filename).resolve()
        if not target.is_relative_to(path.parent.resolve()) or digest(target) != expected:
            raise ValueError("Accepted raw payload changed")
    return manifest


def quality_summaries(root: Path) -> dict[str, Any]:
    """用途各自汇总，禁止同模型同日的validation与production观察混合去重。"""
    return {
        "by_purpose": {
            folder.name: monthly_summary(
                [json.loads(path.read_text()) for path in folder.glob("*/*.json")]
            )
            for folder in (root / "assessments").glob("*")
            if folder.is_dir()
        }
    }


class ReasonGateRejectedError(RuntimeError):
    """停止本批，保留严格观察、精确缺失及失败证据。"""


class FirstResumeReviewRequiredError(RuntimeError):
    """首次次日恢复完成一个目标日后，等待用户审阅具体收据。"""


class HistoryRun:
    """只向指定独立证据库登记capture；验收账本与工作库入库完全分离。"""

    def __init__(self, root: Path, gate_path: Path, env_file: Path) -> None:
        self.root, self.gate_path, self.env_file = root, gate_path, env_file
        self.gate = json.loads(gate_path.read_text())
        self.verify_gate()
        self.calendar = VerifiedTradingCalendar.load(
            Path(self.gate["calendar_path"]), self.gate["inputs"][self.gate["calendar_path"]]
        )
        self.days = self.calendar.payload["trading_days"]
        self.months = monthly_days(self.days)
        self.templates = {
            model: yaml.safe_load(Path(path).read_text())["providers"]["ricequant"]["risk_model"]
            for model, path in self.gate["templates"].items()
        }
        self.provider = build_universe_provider(
            json.loads(Path(self.gate["metadata_path"]).read_text()),
            json.loads(Path(self.gate["reference_path"]).read_text()),
            universe_policy="listed_cn_a_v2",
            mapping_version="alias_v2",
            symbol_rules=symbol_rule_evidence(APPROVED_HISTORY_SYMBOL_RULES_VERSION),
        )
        self.state_path = root / "state.json"
        self.state: dict[str, Any] = (
            json.loads(self.state_path.read_text())
            if self.state_path.exists()
            else {
                "gate_sha256": digest(gate_path),
                "completed": {},
                "observations": {},
                "quota_days": {},
            }
        )
        if self.state["gate_sha256"] != digest(gate_path):
            raise ValueError("Resume gate changed")
        env = load_environment(env_file=env_file)
        self.cfg = load_postgres(env)
        if self.cfg.database != self.gate["evidence_database"] or not self.cfg.database.startswith(
            "getrich_rq_history_"
        ):
            raise ValueError("Dedicated evidence database is required")
        if env.values.get("RICEQUANT_ENABLED", "").lower() not in {"true", "1", "yes"}:
            raise ValueError("RiceQuant must be explicitly enabled")
        self.paths = RawPaths(env.values["RAW_PARQUET_ROOT"])
        if self.paths.root.resolve() != Path(self.gate["raw_root"]).resolve():
            raise ValueError("Raw root changed")
        self.client = RqdatacClient(license_key=env.values["RICEQUANT_API_KEY"], enable_bjse=False)
        self.ctx = RawContext(
            self.paths,
            {"sleep_between_requests_sec": 0.15, "max_retries": 3, "retry_backoff_base_sec": 2},
        )
        self.shared = RicequantImportOptions({}, quota_reserve_fraction=RESERVE)
        self.conn: psycopg.Connection[Any] | None = None

    def verify_gate(self) -> None:
        """源码、既有验收、批准身份、输入与目的地均在SDK/写入前冻结。"""
        if self.root.resolve() != Path(self.gate["run_root"]).resolve():
            raise ValueError("Approved run root differs")
        source = Path(__file__).resolve().parents[4]
        head = subprocess.check_output(
            ["git", "-C", str(source), "rev-parse", "HEAD"], text=True
        ).strip()
        dirty = subprocess.check_output(
            ["git", "-C", str(source), "status", "--porcelain"], text=True
        )
        if (
            head != self.gate["source_head"]
            or dirty
            or get_importer_version(require_clean=True) != self.gate["importer_version"]
        ):
            raise ValueError("Pinned committed source changed")
        import gr_data.raw.ricequant.risk_dynamic as loaded

        if not Path(loaded.__file__).resolve().is_relative_to(source):
            raise ValueError("Loaded source differs from committed checkout")
        if digest(Path(__file__)) != self.gate["runner_sha256"]:
            raise ValueError("Approved runner changed")
        if self.gate["policy_sha256"] != APPROVED_POLICY_SHA256 or self.gate[
            "symbol_rules_sha256"
        ] != symbol_rule_hash(APPROVED_HISTORY_SYMBOL_RULES_VERSION):
            raise ValueError("Approved identity policy changed")
        for filename, expected in self.gate["inputs"].items():
            if digest(Path(filename)) != expected:
                raise ValueError("Frozen input changed: " + Path(filename).name)
        verify_seven_targets(self.gate["old_seven"])
        for row in self.gate["old_seven"]:
            path = Path(row["path"])
            if digest(path) != row["file_sha256"]:
                raise ValueError("Old identity observation changed")
            manifest = json.loads(path.read_text())
            if manifest["identity"]["model"] != row["model"] or manifest["day"] != row["day"]:
                raise ValueError("Old observation model/day differs from required target")
        if (
            self.gate.get("authorization")
            != "user_approved_20261102_identity_monthly_then_raw_only"
        ):
            raise ValueError("Explicit historical raw authorization is absent")

    def options(self, model: str, day: str, purpose: str) -> RiskOptions:
        """仅显式获批入口，2024-01-02只能作为同variant的末端helper。"""
        return parse_risk_options(
            {
                **self.templates[model],
                "model": model,
                "purpose": purpose,
                "start_date": day,
                "end_date": day,
                "universe_policy": "listed_cn_a_v2",
            },
            approved_history_raw=True,
            approved_history_lookahead=day == "2024-01-02",
        )

    def checkpoint(self) -> None:
        save(self.state_path, self.state)

    def quota(self) -> dict[str, Any]:
        """每日首次风险采集前重查；耗尽的唯一恢复依据是实时确认余量。"""
        snapshot = _quota_snapshot(self.client)
        today = datetime.now(ZoneInfo("Asia/Shanghai")).date().isoformat()
        previous = self.state.get("quota_day")
        if previous != today:
            save(self.root / "quota" / (today + "-opening.json"), snapshot)
            self.state["quota_days"][today] = {"opening": snapshot}
            self.state["quota_day"] = today
        self.state["quota_latest"] = snapshot
        if quota_reached(snapshot):
            self.state.update(
                status="paused_quota",
                pause_reason="confirmed_quota_reserve_reached",
                paused_quota_day=today,
            )
            save(self.root / "quota" / (today + "-pause.json"), snapshot)
            self.checkpoint()
            raise BudgetDeferredError("Confirmed daily quota reserve reached")
        paused = self.state.get("paused_quota_day")
        if paused is not None and today > paused and not self.state.get("first_resume_reported"):
            self.state["first_resume_in_progress"] = True
            self.state.setdefault("first_resume_before", snapshot)
        return snapshot

    def raw_path(self, options: RiskOptions) -> Path | None:
        directory = self.paths.ricequant_variant(
            "rq_risk_model", options.contract_version, options.variant_id
        ) / str(options.start_date)
        files = list(directory.glob("*/manifest.json"))
        if len(files) > 1:
            raise ValueError("Ambiguous observation requires explicit selection")
        return files[0] if files else None

    def observe(
        self, model: str, day: str, purpose: str, *, helper: bool = False
    ) -> VerifiedRiskObservation:
        """新raw或init原样复用；capture不表示通过质量或允许业务写入。"""
        self.verify_gate()
        if shutil.disk_usage(self.paths.root).free < 40 * 1024**3:
            raise ValueError("Raw disk free space below 40GiB stop line")
        before = self.quota()
        options = self.options(model, day, purpose)
        validate_universe(self.provider(day), options, date.fromisoformat(day))
        assert self.conn is not None
        prepare_capture(self.conn, options)
        self.state["active_observation"] = {
            "model": model,
            "day": day,
            "purpose": purpose,
            "helper": helper,
        }
        self.checkpoint()
        written = run_risk_raw(
            self.client,
            self.ctx,
            options,
            self.shared,
            mode="init",
            universe_provider=self.provider,
            capture_callback=partial(record_capture, self.conn, options),
        )
        path = self.raw_path(options)
        if path is None:
            raise ValueError("Complete raw observation absent")
        observation = VerifiedRiskObservation.load(path, digest(path), options)
        after = self.quota()
        key = purpose + "/" + model + "/" + day
        self.state["observations"][key] = {
            "manifest": observation.evidence,
            "helper": helper,
            "new_raw_files": written,
        }
        save(
            self.root / "capture-audits" / purpose / model / (day + ".json"),
            {
                "manifest": observation.evidence,
                "quota_before": before,
                "quota_after": after,
                "helper": helper,
                "new_raw_files": written,
            },
        )
        self.checkpoint()
        return observation

    def decision_path(self, purpose: str, result: dict[str, Any]) -> Path:
        """认可收据引用不可变版本；同日重判不能覆盖此前认可的证据。"""
        return (
            self.root
            / "decisions"
            / purpose
            / result["model"]
            / result["day"]
            / (semantic_hash(result) + ".json")
        )

    def assess(
        self, observation: VerifiedRiskObservation, following: VerifiedRiskObservation | None = None
    ) -> dict[str, Any]:
        """所有非已批准原因立即停，helper自身pending不能冒充认可。"""
        result = evaluate_delayed_day(
            observation, calendar=self.calendar, next_observation=following
        )
        purpose = observation.manifest["purpose"]
        path = self.root / "assessments" / purpose / result["model"] / (result["day"] + ".json")
        save(path, result)
        immutable = self.decision_path(purpose, result)
        save(immutable, result)
        if result["status"] == "rejected":
            self.state.update(
                status="stopped_reason_gate",
                rejection={
                    "path": str(immutable),
                    "sha256": digest(immutable),
                    "reasons": result["reject_reasons"],
                },
            )
            self.checkpoint()
            raise ReasonGateRejectedError("Daily reason gate rejected")
        return result

    def target(self, stage: str, model: str, day: str, purpose: str) -> dict[str, Any]:
        """一个目标日只补直接后继；恢复证据不递归扩大采集目标。"""
        if day > "2023-12-31":
            raise ValueError("A lookahead helper cannot become a historical target")
        key = stage + "/" + model + "/" + day
        cached = self.state["completed"].get(key)
        if cached is not None:
            return self.verify_completed(cached, model=model, day=day, purpose=purpose)
        self.state.update(
            stage=stage, active_target={"model": model, "day": day, "purpose": purpose}
        )
        self.checkpoint()
        current = self.observe(model, day, purpose)
        result = self.assess(current)
        if result["status"] == "pending":
            next_day = self.calendar.next_trading_day(day)
            if next_day is None:
                raise ValueError("Complete calendar lacks required next trading day")
            following = self.observe(model, next_day, purpose, helper=True)
            self.assess(following)
            result = self.assess(current, following)
        if result["status"] != "accepted":
            raise ValueError("Target remains pending after direct successor evidence")
        path = self.decision_path(purpose, result)
        record = {"path": str(path), "sha256": digest(path)}
        self.state["completed"][key] = record
        self.checkpoint()
        log.info(
            "Historical target accepted stage=%s model=%s day=%s "
            "complete=%s candidate=%s assessment_sha256=%s",
            stage,
            model,
            day,
            result["complete"],
            result["candidate"],
            record["sha256"],
        )
        if self.state.get("first_resume_in_progress"):
            self.first_resume_report(key, record)
        return result

    def first_resume_report(self, key: str, record: dict[str, Any]) -> None:
        """先落用户确认屏障，再查询报告后快照；任何后快照失败都不能自动续采。"""
        pause = self.root / "quota" / (self.state["paused_quota_day"] + "-pause.json")
        receipt = {
            "status": "awaiting_user_confirmation",
            "before": self.state["first_resume_before"],
            "after": None,
            "completed_target": key,
            "accepted_assessment": record,
            "previous_pause_day": self.state["paused_quota_day"],
            "current_day": self.state["quota_day"],
            "quota_pause_evidence": {"path": str(pause), "sha256": digest(pause)},
        }
        save(self.root / "first-next-day-resume.json", receipt)
        self.state.update(
            status="awaiting_first_resume_confirmation",
            first_resume_reported=True,
            first_resume_in_progress=False,
        )
        self.checkpoint()
        try:
            receipt["after"] = _quota_snapshot(self.client)
        except Exception as exc:
            receipt["after_snapshot_error"] = type(exc).__name__
        save(self.root / "first-next-day-resume.json", receipt)
        raise FirstResumeReviewRequiredError(
            "First next-day resume receipt requires user confirmation"
        )

    def verify_completed(
        self, record: dict[str, Any], *, model: str, day: str, purpose: str
    ) -> dict[str, Any]:
        """只有既有accepted证据及其全部原始文件不变，恢复时才可跳过。"""
        path = Path(record["path"])
        if digest(path) != record["sha256"]:
            raise ValueError("Accepted assessment changed")
        result = json.loads(path.read_text())
        if result["status"] != "accepted" or result["policy_sha256"] != APPROVED_POLICY_SHA256:
            raise ValueError("Accepted assessment policy differs")
        if result["model"] != model or result["day"] != day:
            raise ValueError("Cached assessment model/day differs from ledger key")
        manifest = verify_raw_evidence(result["current_observation"])
        options = self.options(model, day, purpose)
        if (
            manifest["day"] != day
            or manifest["identity"] != options.identity
            or manifest["variant_id"] != options.variant_id
            or manifest["purpose"] != purpose
        ):
            raise ValueError("Cached observation purpose/variant differs from ledger key")
        if result["next_observation"] is not None:
            following = verify_raw_evidence(result["next_observation"])
            if (
                following["identity"] != manifest["identity"]
                or following["variant_id"] != manifest["variant_id"]
                or following["day"] != self.calendar.next_trading_day(day)
            ):
                raise ValueError("Cached successor identity/day differs")
        return result

    def reassess_seven(self) -> None:
        """旧7观察不改判；新观察按新规则复核，并逐接口比较共同原值。"""
        rows = []
        for old in self.gate["old_seven"]:
            model, day = old["model"], old["day"]
            result = self.target("reassessment", model, day, "validation")
            old_path = Path(old["path"])
            old_options = parse_risk_options(
                {
                    **self.templates[model],
                    "model": model,
                    "purpose": "validation",
                    "start_date": day,
                    "end_date": day,
                    "universe_policy": "listed_cn_a_v2",
                },
                historical_probe=True,
            )
            prior = VerifiedRiskObservation.load(old_path, old["file_sha256"], old_options)
            new_path = Path(result["current_observation"]["path"])
            new_manifest = json.loads(new_path.read_text())
            maps = [
                {
                    row["request_code"]: row["canonical_symbol"]
                    for row in manifest["coverage"]
                    if row["request_code"] is not None
                }
                for manifest in (prior.manifest, new_manifest)
            ]
            pieces = {
                piece: compare_piece(
                    pd.read_parquet(old_path.parent / (piece + ".parquet")),
                    pd.read_parquet(new_path.parent / (piece + ".parquet")),
                    maps[0],
                    maps[1],
                    piece,
                )
                for piece in (
                    "exposure",
                    "specific_risk",
                    "specific_return",
                    "factor_return",
                    "covariance",
                )
            }
            rows.append(
                {
                    "model": model,
                    "day": day,
                    "new_status": "accepted",
                    "old_status_preserved": "rejected_under_old_identity_rules",
                    "old_manifest": prior.evidence,
                    "new_assessment": self.state["completed"]["reassessment/" + model + "/" + day],
                    "piece_comparison": pieces,
                }
            )
            save(self.root / "seven-reassessment-progress.json", {"count": len(rows), "rows": rows})
        if len(rows) != 7:
            raise ValueError("Exactly seven old identity observations must be reassessed")
        save(
            self.root / "seven-reassessment.json",
            {"status": "accepted", "count": 7, "old_observations_unchanged": True, "rows": rows},
        )

    def validation_gate(self) -> None:
        """只读冻结准入证据；全部153个月×2及起点五件套后才开放production raw。"""
        seven_path = self.root / "seven-reassessment.json"
        seven = json.loads(seven_path.read_text())
        if seven["status"] != "accepted" or seven["count"] != 7:
            raise ValueError("Seven-observation recheck incomplete")
        expected = ["v2trd_start/v2trd/2011-04-28"] + [
            "monthly/" + model + "/" + day for model in ("v2", "v2trd") for day in self.months
        ]
        axes = []
        for key in expected:
            if key not in self.state["completed"]:
                raise ValueError("Monthly/start-day validation incomplete: " + key)
            _, model, day = key.split("/")
            result = self.verify_completed(
                self.state["completed"][key], model=model, day=day, purpose="validation"
            )
            manifest_path = Path(result["current_observation"]["path"])
            factors = sorted(
                pd.read_parquet(manifest_path.parent / "factor_return.parquet").columns
            )
            industry = sorted(set(factors) - STYLE_FACTORS[result["model"]] - {"comovement"})
            axes.append(
                {
                    "model": result["model"],
                    "day": result["day"],
                    "factor_set_sha256": semantic_hash(factors),
                    "industry_axis_sha256": semantic_hash(industry),
                    "factors": factors,
                    "industries": industry,
                    "manifest": result["current_observation"],
                }
            )
        for old in self.gate["old_seven"]:
            self.verify_completed(
                self.state["completed"]["reassessment/" + old["model"] + "/" + old["day"]],
                model=old["model"],
                day=old["day"],
                purpose="validation",
            )
        changes = axis_changes(axes, self.gate["expected_industry_axis_sha256"])
        axis_path = self.root / "monthly-factor-axes.json"
        save(
            axis_path,
            {"status": "stopped" if changes else "accepted", "rows": axes, "changes": changes},
        )
        if changes:
            raise ValueError("Historical factor axes changed; a new variant review is required")
        save(
            self.root / "production-raw-admission.json",
            {
                "status": "accepted",
                "source_head": self.gate["source_head"],
                "gate_sha256": digest(self.gate_path),
                "seven_reassessment_sha256": digest(seven_path),
                "monthly_model_days": 306,
                "required_accepted_records": {
                    key: self.state["completed"][key] for key in expected
                },
                "factor_axes_sha256": digest(axis_path),
                "source_units_and_numeric_business_acceptance": False,
                "business_ingest_authorized": False,
                "industry_semantics": (
                    "consistent observed factor axes; historical contemporaneous classification "
                    "is unproven and may be backcast sws_2021"
                ),
            },
        )

    def execute(self) -> None:
        """依次完成身份重验、起点、月度、v2→v2trd→v1 raw；失败保持停止。"""
        if self.state.get("status") == "awaiting_first_resume_confirmation":
            raise FirstResumeReviewRequiredError("First resume is awaiting explicit confirmation")
        with psycopg.connect(
            make_pg_dsn(self.cfg), application_name="ricequant_approved_history_raw"
        ) as conn:
            target = conn.execute(
                "SELECT current_database(),"
                "(SELECT system_identifier::text FROM pg_control_system()),"
                "(SELECT oid FROM pg_database WHERE datname=current_database())"
            ).fetchone()
            if target is None or tuple(target) != (
                self.gate["evidence_database"],
                self.gate["system_identifier"],
                self.gate["database_oid"],
            ):
                raise ValueError("Evidence database identity changed")
            conn.execute("SET statement_timeout='30s'")
            conn.execute("SET lock_timeout='10s'")
            conn.commit()
            self.conn = conn
            self.state.update(status="running", pid=os.getpid())
            self.checkpoint()
            self.quota()
            self.reassess_seven()
            self.target("v2trd_start", "v2trd", "2011-04-28", "validation")
            for model in ("v2", "v2trd"):
                for day in self.months:
                    self.target("monthly", model, day, "validation")
                save(
                    self.root / ("monthly-" + model + ".json"),
                    {
                        "status": "accepted",
                        "model": model,
                        "months": 153,
                        "days": self.months,
                        "records": {
                            day: self.state["completed"]["monthly/" + model + "/" + day]
                            for day in self.months
                        },
                    },
                )
            self.validation_gate()
            for model in MODELS:
                for day in (value for value in self.days if STARTS[model] <= value <= "2023-12-31"):
                    self.target("formal_raw", model, day, "production")
                save(
                    self.root / ("raw-complete-" + model + ".json"),
                    {
                        "status": "completed",
                        "model": model,
                        "start": STARTS[model],
                        "end": "2023-12-31",
                        "accepted_target_days": sum(
                            key.startswith("formal_raw/" + model + "/")
                            for key in self.state["completed"]
                        ),
                        "ingested": False,
                    },
                )
            self.state.update(
                status="completed_raw_only", active_target=None, active_observation=None
            )
            self.checkpoint()

    def failure(self, exc: Exception) -> None:
        """仅实查确认的额度触线可跨日续跑；其余错误有证据地停止。"""
        if isinstance(exc, FirstResumeReviewRequiredError):
            return
        if isinstance(exc, BudgetDeferredError):
            try:
                snapshot = _quota_snapshot(self.client)
            except Exception as query_exc:
                self.state.update(
                    status="stopped", quota_confirmation_error=type(query_exc).__name__
                )
            else:
                self.state["quota_latest"] = snapshot
                today = datetime.now(ZoneInfo("Asia/Shanghai")).date().isoformat()
                self.state.update(
                    status="paused_quota" if quota_reached(snapshot) else "stopped",
                    pause_reason="confirmed_quota_reserve_reached"
                    if quota_reached(snapshot)
                    else "unconfirmed_budget_defer",
                    paused_quota_day=today,
                )
                if quota_reached(snapshot):
                    save(self.root / "quota" / (today + "-pause.json"), snapshot)
        elif self.state.get("status") != "stopped_reason_gate":
            self.state["status"] = "stopped"
        self.state["error"] = {
            "type": type(exc).__name__,
            "frames": [
                {"file": Path(row.filename).name, "line": row.lineno, "function": row.name}
                for row in traceback.extract_tb(exc.__traceback__)
            ],
        }
        active = self.state.get("active_observation")
        if active is not None:
            options = self.options(active["model"], active["day"], active["purpose"])
            folder = self.paths.ricequant_variant(
                "rq_risk_model", options.contract_version, options.variant_id
            )
            self.state["failed_raw_receipts"] = [
                {"path": str(path), "sha256": digest(path)}
                for path in folder.glob("_failed/" + active["day"] + "/*/receipt.json")
            ]
        self.checkpoint()


def run_once(root: Path, gate: Path, env_file: Path) -> int:
    """单次尝试连同前置失败都落本次状态，防旧quota暂停被错误重试。"""
    run: HistoryRun | None = None
    try:
        run = HistoryRun(root, gate, env_file)
        if shutil.disk_usage(run.paths.root).free < 40 * 1024**3:
            raise ValueError("Raw disk free space below 40GiB stop line")
        run.execute()
        return 0
    except FirstResumeReviewRequiredError:
        return 3
    except Exception as exc:
        if run is not None:
            run.failure(exc)
        else:
            save(
                root / "preflight-failure.json",
                {
                    "observed_at": datetime.now(timezone.utc).isoformat(),
                    "error_type": type(exc).__name__,
                    "status": "stopped_before_sdk_or_write",
                },
            )
        log.error("Approved history attempt stopped error_type=%s", type(exc).__name__)
        return 1
    finally:
        if run is not None:
            save(root / "monthly-quality.json", quality_summaries(root))


def main() -> None:
    """入口锁覆盖整个有限批次；只对本次新确认quota暂停等待下一上海日期。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-root", type=Path, required=True)
    parser.add_argument("--gate", type=Path, required=True)
    parser.add_argument("--env-file", type=Path, required=True)
    args = parser.parse_args()
    root = args.run_root.resolve()
    root.mkdir(parents=True, exist_ok=True)
    setup_logging(LoggingConfig())
    with (root / ".lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        while True:
            state = root / "state.json"
            before = digest(state) if state.exists() else None
            result = run_once(root, args.gate.resolve(), args.env_file.resolve())
            after = digest(state) if state.exists() else None
            if before == after or after is None:
                raise SystemExit(result or 1)
            payload = json.loads(state.read_text())
            if (
                payload.get("status") != "paused_quota"
                or payload.get("pause_reason") != "confirmed_quota_reserve_reached"
            ):
                raise SystemExit(result)
            pause_day = payload["paused_quota_day"]
            log.info(
                "Approved history quota paused day=%s next_day_refresh_required=true", pause_day
            )
            while datetime.now(ZoneInfo("Asia/Shanghai")).date().isoformat() == pause_day:
                time.sleep(30)


if __name__ == "__main__":
    main()
