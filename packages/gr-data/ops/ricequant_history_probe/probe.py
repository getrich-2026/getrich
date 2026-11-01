"""2024 年前风险数据的显式 validation 探测；不写风险业务表，不批准全量回补。"""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import logging
import os
import re
import subprocess
from collections.abc import Callable, Generator
from contextlib import contextmanager
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from functools import partial
from pathlib import Path
from typing import Any, TypedDict
from uuid import uuid4

import psycopg
import yaml
from gr_data.common.paths import RawPaths
from gr_data.common.retry import PermanentError
from gr_data.common.ricequant_specs import (
    BudgetDeferredError,
    ContractViolationError,
    RawIntegrityError,
    semantic_hash,
)
from gr_data.common.ricequant_symbol_intervals import (
    HISTORY_SYMBOL_RULES_VERSION,
    symbol_rule_evidence,
)
from gr_data.common.ricequant_universe import (
    build_universe_provider,
    load_metadata_snapshot,
    reference_input_codes,
)
from gr_data.config.ricequant import RicequantImportOptions
from gr_data.config.ricequant_risk import RiskOptions, parse_risk_options
from gr_data.config.settings import load_postgres, make_pg_dsn
from gr_data.db.risk_receipts import get_importer_version, prepare_capture, record_capture
from gr_data.raw.base import RawContext
from gr_data.raw.ricequant.client import RqdatacClient
from gr_data.raw.ricequant.fetchers.supplements import _check_quota
from gr_data.raw.ricequant.risk_shapes import STYLE_FACTORS
from gr_data.raw.ricequant.riskmodel import _quota_snapshot, read_bundles, run_risk_raw
from gr_tools.config import load_environment


log = logging.getLogger(__name__)
MODELS = ("v1", "v2", "v2trd")
REGISTRATION_GUARDED_CODE_CHANGES = (
    {
        "old_symbol": "600849.SH",
        "new_symbol": "601607.SH",
        "effective_date": "2010-03-05",
        "evidence_url": "https://static.sse.com.cn/cs/zhs/scfw/gg/ssgs/2011-03-09/601607_2010_n.pdf",
        "classification": "surviving_entity_code_change_during_absorption_merger",
        "absorbed_symbols_must_remain_separate": ["600607.SH", "600842.SH"],
    },
    {
        "old_symbol": "601313.SH",
        "new_symbol": "601360.SH",
        "effective_date": "2018-02-28",
        "evidence_url": "https://static.cninfo.com.cn/finalpage/2018-02-02/1204386750.PDF",
        "completion_evidence_url": "https://static.cninfo.com.cn/finalpage/2018-02-28/1204434951.PDF",
        "classification": "surviving_entity_code_change_after_restructuring",
    },
)
REPRESENTATIVE_DAYS = ("2010-01-04", "2014-01-06", "2017-01-04", "2020-01-06", "2023-01-04")


class CaptureEvidenceError(RuntimeError):
    """raw 已存在但数据库 capture 证据失败，必须整批停止。"""


class QuotaSnapshot(TypedDict):
    observed_at: str
    bytes_used: int | float
    bytes_limit: int | float


def quota_snapshot(client: RqdatacClient) -> QuotaSnapshot:
    """复用现有配额白名单校验，并向审计边界提供窄数值类型。"""
    raw = _quota_snapshot(client)
    used, limit = raw["bytes_used"], raw["bytes_limit"]
    assert isinstance(used, (int, float)) and isinstance(limit, (int, float))
    return {"observed_at": str(raw["observed_at"]), "bytes_used": used, "bytes_limit": limit}


@contextmanager
def stopped_on_failure(path: Path, state: dict[str, Any]) -> Generator[None]:
    """任何未完成探测失败都落状态，保留已验收段以供显式恢复。"""
    try:
        yield
    except Exception as exc:
        state.update(status="stopped", error_type=type(exc).__name__)
        save(path, state)
        raise


def digest(path: Path) -> str:
    """文件字节 SHA-256。"""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save(path: Path, value: dict[str, Any]) -> None:
    """审计结果原子替换；无任何账户凭据。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp-" + uuid4().hex)
    try:
        temporary.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2))
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def bind_input(path: Path, state: dict[str, Any], *, expected: str | None = None) -> None:
    """输入首次绑定后不可变；外部预置快照可由批准门禁提供初始哈希。"""
    actual = digest(path)
    hashes = state.setdefault("input_sha256", {})
    frozen = hashes.get(str(path.resolve()), expected)
    if frozen is not None and actual != frozen:
        raise ValueError("Frozen probe input changed: " + path.name)
    hashes[str(path.resolve())] = actual


def make_plan() -> dict[str, Any]:
    """固定探测窗口；代表日须由实际交易日历再次确认，不擅自前移。"""
    windows = [
        {"key": f"representative-{day[:4]}", "start": day, "end": day}
        for day in REPRESENTATIVE_DAYS
    ]
    windows += [
        {"key": "month-2023-01", "start": "2023-01-01", "end": "2023-01-31"},
        # 同时观察 2021 版行业实施附近及用户要求的 2021-12 跨月边界。
        {"key": "industry-2021-11", "start": "2021-11-26", "end": "2021-12-03"},
        {"key": "industry-2021-12-mid", "start": "2021-12-10", "end": "2021-12-13"},
        {"key": "industry-2021-12", "start": "2021-12-27", "end": "2022-01-07"},
    ]
    return {
        "schema_version": 1,
        "stage": "probe_only",
        "target_start": "2010-01-04",
        "target_end": "2023-12-31",
        "purpose": "validation",
        "models": list(MODELS),
        "industry_mapping": "sws_2021",
        "symbol_rules": symbol_rule_evidence(HISTORY_SYMBOL_RULES_VERSION),
        "additional_code_changes_require_registered_aliases": list(
            REGISTRATION_GUARDED_CODE_CHANGES
        ),
        "jobs": [{**window, "model": model} for model in MODELS for window in windows],
        "formal_collection_authorized": False,
        "working_database_ingest_authorized": False,
        "start_dates_require_user_confirmation": True,
        "sparse_samples_prove_full_year_completeness": False,
    }


def options_for_job(template: dict[str, Any], job: dict[str, str]) -> RiskOptions:
    """保留原单位声明作为待复核假设，创建独立、不可转 production 的探测身份。"""
    data = {
        **template,
        "purpose": "validation",
        "universe_policy": "listed_cn_a_v2",
        "model": job["model"],
        "industry_mapping": "sws_2021",
        "start_date": job["start"],
        "end_date": job["end"],
    }
    return parse_risk_options(data, historical_probe=True)


def unresolved_identity_issues(
    snapshot: dict[str, Any], job: dict[str, str]
) -> list[dict[str, Any]]:
    """已知真实换码未登记时阻断受影响区间，不能静默用现 canonical 回填。"""
    issues = []
    approved = symbol_rule_evidence(HISTORY_SYMBOL_RULES_VERSION)["rules"]
    canonical = {row["symbol"]: row["instrument_id"] for row in snapshot["instruments"]}
    aliases = {
        row["source_symbol"]: row["instrument_id"]
        for row in snapshot["aliases"]
        if row["source"] == "tushare"
    }
    for change in REGISTRATION_GUARDED_CODE_CHANGES:
        if any(
            rule["old_source_symbol"] == change["old_symbol"]
            and rule["new_source_symbol"] == change["new_symbol"]
            and rule["effective_date"] == change["effective_date"]
            for rule in approved
        ) and (
            canonical.get(change["new_symbol"]) is not None
            and aliases.get(change["old_symbol"]) == canonical[change["new_symbol"]]
            and canonical.get(change["old_symbol"], canonical[change["new_symbol"]])
            == canonical[change["new_symbol"]]
            and aliases.get(change["new_symbol"], canonical[change["new_symbol"]])
            == canonical[change["new_symbol"]]
        ):
            continue
        last_old_day = date.fromisoformat(change["effective_date"]) - timedelta(days=1)
        relevant = []
        for row in snapshot["instruments"]:
            if row["symbol"] not in {change["old_symbol"], change["new_symbol"]}:
                continue
            start = date.fromisoformat(job["start"])
            if row.get("list_date"):
                start = max(start, date.fromisoformat(row["list_date"]))
            end = min(date.fromisoformat(job["end"]), last_old_day)
            if row.get("delist_date"):
                end = min(end, date.fromisoformat(row["delist_date"]) - timedelta(days=1))
            if start <= end:
                relevant.append(
                    {
                        "instrument_id": row["instrument_id"],
                        "canonical_symbol": row["symbol"],
                        "affected_range": [str(start), str(end)],
                    }
                )
        if relevant:
            issues.append(
                {
                    **change,
                    "status": "blocked_identity",
                    "affected": relevant,
                    "new_aliases_created": 0,
                }
            )
    return issues


def alias_inventory(snapshot: dict[str, Any]) -> dict[str, Any]:
    """完整代码别名只列候选，不新增映射；未核实的有效期不能由 SDK 推断。"""
    canonical = {row["instrument_id"]: row["symbol"] for row in snapshot["instruments"]}
    rules = symbol_rule_evidence(HISTORY_SYMBOL_RULES_VERSION)["rules"]
    verified = {(r["old_source_symbol"], r["new_source_symbol"]) for r in rules}
    candidates = sorted(
        {
            (row["source_symbol"], canonical[row["instrument_id"]])
            for row in snapshot["aliases"]
            if row["source"] == "tushare"
            and row["instrument_id"] in canonical
            and row["source_symbol"] != canonical[row["instrument_id"]]
        }
    )
    return {
        "metadata_hash": semantic_hash(snapshot),
        "verified_rules": rules,
        "unresolved_real_code_changes": unresolved_identity_issues(
            snapshot, {"start": "2010-01-04", "end": "2023-12-31"}
        ),
        "other_candidates": [
            {"old_symbol": old, "canonical_symbol": new, "status": "needs_identity_and_date_review"}
            for old, new in candidates
            if (old, new) not in verified
        ],
        "manual_review_limit": 5,
        "new_aliases_created": 0,
        "external_review_candidates": [
            {
                "old_symbol": "000527.SZ",
                "new_symbol": "000333.SZ",
                "classification": "absorption_merger_not_simple_code_alias",
                "evidence_url": "https://www.szse.cn/disclosure/notice/general/t20130912_501128.html",
                "action": "keep_separate_identities_no_automatic_mapping",
            },
            {
                "old_symbol": "000562.SZ",
                "new_symbol": "000166.SZ",
                "classification": "absorption_merger_not_simple_code_alias",
                "evidence_url": "https://www.cnindex.com.cn/zh_information/notices_news/2015/201501/P020191213391347017654.pdf",
                "action": "keep_separate_identities_no_automatic_mapping",
            },
            {
                "old_symbol": "000916.SZ",
                "new_symbol": "001965.SZ",
                "classification": "absorption_merger_not_simple_code_alias",
                "evidence_url": "https://www.cnindex.com.cn/zh_information/notices_news/2017/201712/P020191213349332464586.pdf",
                "action": "keep_separate_identities_no_automatic_mapping",
            },
            {
                "old_symbol": "600991.SH",
                "new_symbol": "601238.SH",
                "classification": "absorption_merger_not_simple_code_alias",
                "evidence_url": "https://www1.hkexnews.hk/listedco/listconews/sehk/2012/1010/ltn20121010410_c.pdf",
                "action": "keep_separate_identities_no_automatic_mapping",
            },
            {
                "old_symbol": "000024.SZ",
                "new_symbol": "001979.SZ",
                "classification": "absorption_merger_not_simple_code_alias",
                "evidence_url": "https://www.cnindex.com.cn/zh_information/notices_news/2015/201512/P020191213391402705208.pdf",
                "action": "keep_separate_identities_no_automatic_mapping",
            },
            {
                "old_symbol": "600087.SH",
                "new_symbol": "601975.SH",
                "classification": "delisting_then_relisting_requires_separate_intervals_review",
                "evidence_url": "https://edu.sse.com.cn/attention/c/4747935.shtml",
                "action": "needs_original_listing_and_delisting_boundaries_no_automatic_mapping",
            },
        ],
        "exhaustive_historical_code_change_inventory": False,
        "limitation": "Only aliases already registered in the frozen metadata are scanned",
    }


def verify_start_gate(gate: dict[str, Any], plan_hash: str, version: str) -> None:
    """现有导入全量验收后才可探测；起点确认和正式采集仍是下一道门禁。"""
    if (
        gate.get("stage") != "probe_only"
        or gate.get("plan_sha256") != plan_hash
        or gate.get("source_commit") != version
    ):
        raise ValueError("Probe approval identity differs from the frozen plan/source")
    acceptance = Path(gate["current_replay_acceptance_path"])
    if digest(acceptance) != gate.get("current_replay_acceptance_sha256"):
        raise ValueError("Current replay acceptance hash changed")
    evidence = json.loads(acceptance.read_text())
    if evidence.get("status") != "completed" or evidence.get("verified_model_days") != 2028:
        raise ValueError("Current 2028-model-day replay is not fully accepted")


def verify_source_gate(gate: dict[str, Any], repo: Path, script: Path) -> None:
    """ops 执行器另钉 HEAD／文件哈希／干净目录，不改 importer_version 的既有定义。"""
    expected_head = gate.get("source_head_commit")
    if not isinstance(expected_head, str) or not re.fullmatch(r"[0-9a-f]{40}", expected_head):
        raise ValueError("Probe requires a full committed source HEAD")
    if digest(script) != gate.get("probe_sha256"):
        raise ValueError("Probe runner hash changed")
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=repo, capture_output=True, text=True, check=True
    ).stdout.strip()
    status = subprocess.run(
        [
            "git",
            "status",
            "--porcelain",
            "--untracked-files=all",
            "--",
            "packages/gr-data/ops/ricequant_history_probe",
        ],
        cwd=repo,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    if head != expected_head or status.strip():
        raise ValueError("Probe HEAD changed or ops directory contains uncommitted changes")


def verify_raw_root(value: str, gate: dict[str, Any]) -> Path:
    """只钉非敏感的绝对 raw 路径；恢复不允许同账本跨根。"""
    path = Path(value)
    approved = Path(gate["raw_parquet_root"])
    if not path.is_absolute() or not approved.is_absolute() or path.resolve() != approved.resolve():
        raise ValueError("Probe raw parquet root differs from the approved absolute path")
    return path.resolve()


def verify_evidence_database(conn: psycopg.Connection, gate: dict[str, Any]) -> None:
    """在任何写入或 SDK 初始化前钉住独立证据库及 PG 集群身份。"""
    identity = conn.execute(
        "SELECT current_database(), (SELECT system_identifier::text FROM pg_control_system()), "
        "(SELECT oid FROM pg_database WHERE datname=current_database())"
    ).fetchone()
    expected = (
        gate["evidence_database"],
        gate["evidence_system_identifier"],
        gate["evidence_database_oid"],
    )
    if (
        identity is None
        or tuple(identity) != expected
        or not expected[0].startswith("getrich_rq_history_")
    ):
        raise ValueError("Dedicated evidence database identity differs from the approved target")
    conn.commit()


def summarize_observation(manifest: dict[str, Any], frames: dict[str, Any]) -> dict[str, Any]:
    """保留全部因子轴和覆盖分母；轴相同不等于历史行业分类语义已证实。"""
    model = manifest["identity"]["model"]
    factors = list(frames["exposure"].columns)
    industries = [
        factor for factor in factors if factor not in STYLE_FACTORS[model] | {"comovement"}
    ]
    return {
        "day": manifest["day"],
        "observation_id": manifest["observation_id"],
        "variant_id": manifest["variant_id"],
        "manifest_hash": semantic_hash(manifest),
        "files": manifest["files"],
        "coverage_counts": manifest["coverage_counts"],
        "factor_axis": factors,
        "industry_factors": industries,
        "industry_axis_hash": semantic_hash(sorted(industries)),
        "quota_observation": manifest["quota_observation"],
        "source_units_verified_for_this_historical_period": False,
    }


def execute_job(
    client: RqdatacClient,
    ctx: RawContext,
    options: RiskOptions,
    shared: RicequantImportOptions,
    provider: Callable[[str], dict[str, Any]],
    capture: Callable[[dict], None],
) -> dict[str, Any]:
    """仅走现有严格 raw writer；失败不发布假完整观察，不写五件套业务表。"""
    _check_quota(client, shared.quota_reserve_fraction)
    before = quota_snapshot(client)
    days = [
        str(value)
        for value in client.get_trading_dates(str(options.start_date), str(options.end_date))
    ]
    if (
        not days
        or len(days) != len(set(days))
        or any(
            not options.start_date <= date.fromisoformat(day) <= options.end_date for day in days
        )
    ):
        raise RawIntegrityError("Probe calendar is empty, duplicated or out of scope")

    def capture_evidence(manifest: dict[str, Any]) -> None:
        try:
            capture(manifest)
        except Exception as exc:
            raise CaptureEvidenceError("Probe capture evidence failed; raw is retained") from exc

    observations = []
    failures = []
    newly_fetched_days = []
    for day in sorted(days):
        daily = replace(
            options, start_date=date.fromisoformat(day), end_date=date.fromisoformat(day)
        )
        try:
            written = run_risk_raw(
                client,
                ctx,
                daily,
                shared,
                mode="init",
                universe_provider=provider,
                capture_callback=capture_evidence,
            )
            bundles = list(read_bundles(ctx.paths, daily))
            if len(bundles) != 1:
                raise RawIntegrityError("Probe day must have exactly one complete observation")
            observations.append(summarize_observation(*bundles[0]))
            if written > 0:
                newly_fetched_days.append(day)
        except (ContractViolationError, RawIntegrityError) as exc:
            root = ctx.paths.ricequant_variant(
                "rq_risk_model", daily.contract_version, daily.variant_id
            )
            receipts = sorted(root.glob(f"_failed/{day}/*/receipt.json"))
            failures.append(
                {
                    "day": day,
                    "error_type": type(exc).__name__,
                    "receipts": [{"path": str(path), "sha256": digest(path)} for path in receipts],
                }
            )
            log.warning(
                "Probe day failed model=%s day=%s error_type=%s",
                options.model,
                day,
                type(exc).__name__,
            )
        # 权限、额度、网络等请求边界失败交由整批停止，不伪装成历史缺口。
    after = quota_snapshot(client)
    same_counter_window = (
        before["bytes_limit"] == after["bytes_limit"]
        and after["bytes_used"] >= before["bytes_used"]
    )
    return {
        "model": options.model,
        "range": [str(options.start_date), str(options.end_date)],
        "variant_id": options.variant_id,
        "expected_days": days,
        "newly_fetched_days": newly_fetched_days,
        "newly_fetched_candidate_days": sum(
            row["coverage_counts"]["candidate"]
            for row in observations
            if row["day"] in newly_fetched_days
        ),
        "observations": observations,
        "failures": failures,
        "calendar_complete": len(observations) == len(days) and not failures,
        "all_candidates_complete": bool(observations)
        and not failures
        and all(
            row["coverage_counts"]["complete"] == row["coverage_counts"]["candidate"]
            for row in observations
        ),
        "quota_before": before,
        "quota_after": after,
        "account_counter_delta": after["bytes_used"] - before["bytes_used"]
        if same_counter_window
        else None,
        "counter_delta_is_exact_request_cost": False,
        "remaining_bytes": after["bytes_limit"] - after["bytes_used"],
        "units_and_numeric_acceptance_require_verified_tushare_history": True,
    }


def quota_estimate(reports: list[dict[str, Any]]) -> dict[str, Any]:
    """按新增模型日和候选日给出经验区间，零增量不视为免费，重置窗口剔除。"""
    per_day, per_candidate = [], []
    unmeasurable = 0
    for report in reports:
        delta = report.get("account_counter_delta")
        days = len(report.get("newly_fetched_days", []))
        candidates = report.get("newly_fetched_candidate_days", 0)
        if delta is None or delta <= 0 or days <= 0 or candidates <= 0:
            unmeasurable += 1
            continue
        per_day.append(delta / days)
        per_candidate.append(delta / candidates)
    return {
        "observed_bytes_per_new_model_day_range": [min(per_day), max(per_day)] if per_day else None,
        "observed_bytes_per_candidate_day_range": [min(per_candidate), max(per_candidate)]
        if per_candidate
        else None,
        "measured_positive_windows": len(per_day),
        "unmeasurable_or_reused_windows": unmeasurable,
        "zero_delta_means_free": False,
        "exact_request_cost": False,
        "limitations": [
            "provider_accounting_can_lag",
            "counter_reset_windows_excluded",
            "reference_and_calendar_overhead",
            "candidate_count_changes_by_year",
        ],
    }


def summarize_reports(reports: list[dict[str, Any]]) -> dict[str, Any]:
    """汇总稀疏探测证据；不把代表日通过误写成整年完整或行业语义连续。"""
    models = {}
    for model in MODELS:
        samples = {
            row["day"]: row
            for report in reports
            if report["model"] == model
            for row in report["observations"]
        }
        ordered = sorted(samples.values(), key=lambda row: row["day"])
        transitions = [
            {
                "last_sample": before["day"],
                "first_sample": after["day"],
                "before_industry_axis": before["industry_factors"],
                "after_industry_axis": after["industry_factors"],
                "exact_switch_date_confirmed": False,
            }
            for before, after in zip(ordered, ordered[1:], strict=False)
            if before["industry_axis_hash"] != after["industry_axis_hash"]
        ]
        complete_samples = [
            row["day"]
            for row in ordered
            if row["coverage_counts"]["complete"] == row["coverage_counts"]["candidate"]
        ]
        models[model] = {
            "earliest_complete_sample": min(complete_samples, default=None),
            "unique_observations": len(ordered),
            "all_candidates_complete_observations": len(complete_samples),
            "industry_axis_changes_between_samples": transitions,
            "industry_semantic_continuity_confirmed": False,
            "full_year_start_confirmed": False,
            "identity_blocked_segments": [
                report["identity_blockers"]
                for report in reports
                if report["model"] == model and report.get("status") == "blocked_identity"
            ],
            "failed_days": [
                row for report in reports if report["model"] == model for row in report["failures"]
            ],
            "quota_estimate": quota_estimate(
                [report for report in reports if report["model"] == model]
            ),
            "quota_account_counter_deltas": [
                report["account_counter_delta"] for report in reports if report["model"] == model
            ],
        }
    return {
        "stage": "awaiting_start_date_review",
        "models": models,
        "formal_collection_authorized": False,
        "working_database_ingest_authorized": False,
        "counter_delta_is_exact_request_cost": False,
        "next_step": (
            "Review model availability, confirm any industry cutover "
            "and each full-year start before formal collection"
        ),
    }


def main() -> None:
    """默认只生成计划；执行必须显式提供全量重放验收门禁和独立证据库。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-root", required=True, type=Path)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--gate", type=Path)
    parser.add_argument("--env-file", type=Path)
    parser.add_argument("--template-root", type=Path)
    args = parser.parse_args()
    root = args.run_root.resolve()
    root.mkdir(parents=True, exist_ok=True)
    plan = make_plan()
    plan_path = root / "plan.json"
    if plan_path.exists():
        if json.loads(plan_path.read_text()) != plan:
            raise ValueError("Frozen probe plan changed")
    else:
        save(plan_path, plan)
    if not args.execute:
        print(
            json.dumps(
                {
                    "plan": str(plan_path),
                    "sha256": digest(plan_path),
                    "stage": "prepared_not_started",
                }
            )
        )
        return
    if args.gate is None or args.env_file is None or args.template_root is None:
        parser.error("execute requires gate, env-file and template-root")
    version = get_importer_version(require_clean=True)
    gate = json.loads(args.gate.read_text())
    verify_start_gate(gate, digest(plan_path), version)
    verify_source_gate(gate, Path(__file__).resolve().parents[4], Path(__file__).resolve())
    env = load_environment(env_file=args.env_file)
    cfg = load_postgres(env)
    if (
        not cfg.database.startswith("getrich_rq_history_")
        or cfg.database != gate["evidence_database"]
    ):
        raise ValueError("Probe requires a dedicated evidence database")
    if env.values.get("RICEQUANT_ENABLED", "").lower() not in {"true", "1", "yes"}:
        raise ValueError("RiceQuant must be explicitly enabled")
    license_key = env.values.get("RICEQUANT_API_KEY", "")
    if not license_key:
        raise ValueError("RiceQuant credentials are missing")
    raw_root = verify_raw_root(env.values["RAW_PARQUET_ROOT"], gate)
    template_paths = {model: args.template_root / f"{model}.yaml" for model in MODELS}
    shared = RicequantImportOptions({}, quota_reserve_fraction=0.1)
    client = RqdatacClient(license_key=license_key, enable_bjse=False)
    ctx = RawContext(
        RawPaths(raw_root),
        {"sleep_between_requests_sec": 0.15, "max_retries": 3, "retry_backoff_base_sec": 2},
    )
    state_path = root / "state.json"
    state = (
        json.loads(state_path.read_text())
        if state_path.exists()
        else {"stage": "probe_only", "completed": {}, "source_commit": version}
    )
    if state["source_commit"] != version:
        raise ValueError("Probe source changed; new batch identity required")
    runtime_identity = {
        "raw_parquet_root": str(raw_root.resolve()),
        "evidence_database": cfg.database,
        "evidence_system_identifier": gate["evidence_system_identifier"],
        "evidence_database_oid": gate["evidence_database_oid"],
        "source_head_commit": gate["source_head_commit"],
        "probe_sha256": gate["probe_sha256"],
    }
    if state.get("runtime_identity", runtime_identity) != runtime_identity:
        raise ValueError("Probe runtime target or source identity changed")
    state["runtime_identity"] = runtime_identity
    with (root / ".lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        bind_input(plan_path, state)
        for path in template_paths.values():
            bind_input(path, state)
        save(state_path, state)
        templates = {
            model: yaml.safe_load(path.read_text())["providers"]["ricequant"]["risk_model"]
            for model, path in template_paths.items()
        }
        with (
            stopped_on_failure(state_path, state),
            psycopg.connect(make_pg_dsn(cfg), application_name="ricequant_history_probe") as conn,
        ):
            verify_evidence_database(conn, gate)
            conn.execute("SET statement_timeout='30s'")
            conn.execute("SET lock_timeout='10s'")
            conn.commit()
            with conn.transaction():
                conn.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
                snapshot = load_metadata_snapshot(conn)
            snapshot_path = root / "metadata.json"
            if snapshot_path.exists():
                bind_input(snapshot_path, state, expected=gate.get("metadata_sha256"))
                snapshot = json.loads(snapshot_path.read_text())
            else:
                save(snapshot_path, snapshot)
                bind_input(snapshot_path, state, expected=gate.get("metadata_sha256"))
            save(state_path, state)
            save(root / "alias-inventory.json", alias_inventory(snapshot))
            blocked_jobs = {
                job["model"] + "/" + job["key"]: issues
                for job in plan["jobs"]
                if (issues := unresolved_identity_issues(snapshot, job))
            }
            if blocked_jobs:
                # 没有已登记的旧代码身份时，整个参考名单也不能通过原严格重建；
                # 在 SDK 初始化前留证，等待独立证据库完成受审登记后另行固定快照。
                save(
                    root / "identity-preflight.json",
                    {
                        "status": "blocked_identity",
                        "jobs": blocked_jobs,
                        "is_model_data_unavailable": False,
                    },
                )
                state.update(status="blocked_identity", active_job=None)
                save(state_path, state)
                return
            reference_path = root / "reference.json"
            if reference_path.exists():
                if str(reference_path.resolve()) not in state.get("input_sha256", {}):
                    raise ValueError(
                        "Existing reference snapshot is not bound; review before resuming"
                    )
                bind_input(reference_path, state)
                reference = json.loads(reference_path.read_text())
            else:
                try:
                    reference = client.risk_reference(
                        reference_input_codes(snapshot),
                        quota_guard=lambda: _check_quota(client, shared.quota_reserve_fraction),
                    )
                    save(reference_path, reference)
                    bind_input(reference_path, state)
                    save(state_path, state)
                except Exception as exc:
                    save(
                        root / "reference-failure.json",
                        {
                            "error_type": type(exc).__name__,
                            "observed_at": datetime.now(timezone.utc).isoformat(),
                        },
                    )
                    raise
            provider = build_universe_provider(
                snapshot,
                reference,
                universe_policy="listed_cn_a_v2",
                mapping_version="alias_v2",
                symbol_rules=plan["symbol_rules"],
            )
            state.pop("error_type", None)
            state.update(status="running", pid=os.getpid())
            save(state_path, state)
            for job in plan["jobs"]:
                verify_source_gate(
                    gate, Path(__file__).resolve().parents[4], Path(__file__).resolve()
                )
                if get_importer_version(require_clean=True) != version:
                    raise ValueError("Probe importer source changed during execution")
                for input_path in state["input_sha256"]:
                    bind_input(Path(input_path), state)
                key = job["model"] + "/" + job["key"]
                if key in state["completed"]:
                    report = root / state["completed"][key]["path"]
                    if digest(report) != state["completed"][key]["sha256"]:
                        raise ValueError("Completed probe evidence changed")
                    continue
                options = options_for_job(templates[job["model"]], job)
                state.update(active_job=key)
                save(state_path, state)
                blockers = unresolved_identity_issues(snapshot, job)
                if blockers:
                    report_value = {
                        "status": "blocked_identity",
                        "model": job["model"],
                        "range": [job["start"], job["end"]],
                        "identity_blockers": blockers,
                        "observations": [],
                        "failures": [],
                        "calendar_complete": False,
                        "all_candidates_complete": False,
                        "account_counter_delta": None,
                        "remaining_bytes": None,
                        "newly_fetched_days": [],
                        "newly_fetched_candidate_days": 0,
                        "is_model_data_unavailable": False,
                    }
                    log.warning("Probe identity blocked model=%s key=%s", job["model"], job["key"])
                else:
                    prepare_capture(conn, options)
                    try:
                        report_value = execute_job(
                            client,
                            ctx,
                            options,
                            shared,
                            provider,
                            partial(record_capture, conn, options),
                        )
                    except (BudgetDeferredError, PermanentError, ConnectionError) as exc:
                        state.update(
                            status="stopped", active_job=key, error_type=type(exc).__name__
                        )
                        save(state_path, state)
                        raise
                report_path = root / "reports" / (key.replace("/", "-") + ".json")
                save(report_path, report_value)
                state["completed"][key] = {
                    "path": str(report_path.relative_to(root)),
                    "sha256": digest(report_path),
                }
                save(state_path, state)
                log.info(
                    "Probe segment completed model=%s key=%s complete=%s "
                    "remaining_bytes=%s sha256=%s",
                    options.model,
                    job["key"],
                    report_value["all_candidates_complete"],
                    report_value["remaining_bytes"],
                    digest(report_path),
                )
            save(
                root / "summary.json",
                summarize_reports(
                    [
                        json.loads((root / item["path"]).read_text())
                        for item in state["completed"].values()
                    ]
                ),
            )
            state.update(
                status="awaiting_start_date_review",
                active_job=None,
                formal_collection_authorized=False,
            )
            save(state_path, state)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    main()
