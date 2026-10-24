"""米筐生产回补：固定范围、月度组织、逐日验收；只记录安全元数据。"""

from __future__ import annotations

import argparse
import calendar as calendar_module
import fcntl
import hashlib
import json
import os
import re
import subprocess
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any
from uuid import uuid4
from zoneinfo import ZoneInfo

import yaml


if TYPE_CHECKING:
    from gr_tools.config import Environment


BASE = Path(__file__).resolve().parent
REPO = Path("/Volumes/myssd/project/getrich")
SEED = Path("/tmp/getrich-rq-production-20261023")
START = date(2024, 1, 30)
END = date(2026, 10, 21)
MODELS = ("v1", "v2", "v2trd")
IMPORTER_VERSION = "aa54d8063b2d933b35742339a2e8ed408a0b5745"
ACCOUNT_ENV = "RICEQUANT_API_KEY"
QUOTA_RESERVE = 0.1
QUOTA_NOTE = (
    "Account counters may lag or reset and include other consumers. "
    "Zero delta is not zero transfer; per-job deltas are observations, not final billing."
)


class StopRunError(RuntimeError):
    def __init__(self, reason: str, *, quota: bool = False):
        super().__init__(reason)
        self.reason = reason
        self.quota = quota


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def local_day() -> str:
    return datetime.now(ZoneInfo("Asia/Shanghai")).date().isoformat()


def require(condition: bool, reason: str) -> None:
    if not condition:
        raise StopRunError(reason)


def atomic_json(path: Path, value: Any) -> None:
    atomic_text(path, json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n")


def atomic_text(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp-" + uuid4().hex)
    try:
        with temporary.open("w", encoding="utf-8") as handle:
            handle.write(value)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def month_limit(value: str | None) -> date:
    if value is None:
        return END
    require(bool(re.fullmatch(r"\d{4}-\d{2}", value)), "invalid_through_month")
    try:
        year, month = map(int, value.split("-"))
        last = date(year, month, calendar_module.monthrange(year, month)[1])
    except ValueError:
        raise StopRunError("invalid_through_month") from None
    require("2024-01" <= value <= "2026-10", "through_month_outside_fixed_range")
    return min(last, END)


def load_templates(base: Path) -> tuple[dict[str, dict], dict[str, str]]:
    from gr_data.config.ricequant_risk import parse_risk_options

    templates, variants = {}, {}
    for model in MODELS:
        target = base / "templates" / f"{model}.yaml"
        source = target if target.exists() else SEED / f"{model}.yaml"
        require(source.is_file(), "template_missing")
        text = source.read_text(encoding="utf-8")
        data = yaml.safe_load(text)
        require(isinstance(data, dict) and set(data) == {"providers"}, "template_root_invalid")
        require(set(data["providers"]) == {"ricequant"}, "template_provider_invalid")
        provider = data["providers"]["ricequant"]
        require(
            set(provider) <= {"license_env", "risk_model", "rate_limit"},
            "template_has_unexpected_fields",
        )
        require(provider.get("license_env") == ACCOUNT_ENV, "template_account_changed")
        options = parse_risk_options(provider["risk_model"])
        require(
            options.model == model
            and options.purpose == "production"
            and options.universe_policy == "listed_cn_a_v2",
            "template_identity_invalid",
        )
        templates[model], variants[model] = data, options.variant_id
        if not target.exists():
            atomic_text(target, text)
    return templates, variants


def import_baseline(base: Path) -> dict:
    """首次冻结前 20 日历史验收摘要；不是本执行器新采集或实时复查。"""
    target = base / "baseline.json"
    if target.exists():
        return json.loads(target.read_text())
    source = SEED / "batches.json"
    result = {"status": "historical_snapshot", "jobs": [], "pending_ipos": []}
    if source.exists():
        old = json.loads(source.read_text())
        require(old.get("importer_version") == IMPORTER_VERSION, "baseline_importer_changed")
        for entry in old.get("batches", []):
            if entry.get("day", "") >= str(START) or entry.get("audit_exit") != 0:
                continue
            require(
                entry.get("raw_exit") == 0 and entry.get("ingest_exit") == 0,
                "baseline_not_successful",
            )
            audit_path = SEED / entry["day"] / f"{entry['model']}-audit.json"
            require(audit_path.is_file(), "baseline_audit_missing")
            audit = json.loads(audit_path.read_text())["models"][0]
            require(audit.get("status") == "passed", "baseline_audit_failed")
            gaps = audit.get("not_included_candidates", [])
            require(
                all(
                    row["status"] == "partial_bundle"
                    and row["pieces"]
                    == {"exposure": True, "specific_risk": True, "specific_return": False}
                    for row in gaps
                ),
                "baseline_unknown_gap_pattern",
            )
            result["jobs"].append(
                {
                    **{
                        key: entry.get(key)
                        for key in (
                            "day",
                            "model",
                            "coverage_counts",
                            "quota_before",
                            "quota_after",
                            "run_id",
                        )
                    },
                    "status": "baseline_passed",
                    "import_evidence": audit["import_evidence"],
                    "known_ipo_ids": [row["instrument_id"] for row in gaps],
                    "known_ipo_basis": (
                        "Previously approved first-20-day audit; do not infer "
                        "new IPO eligibility from this historical summary."
                    ),
                }
            )
        for model in MODELS:
            jobs = [job for job in result["jobs"] if job["model"] == model]
            if jobs:
                last = max(jobs, key=lambda job: job["day"])
                for iid in last["known_ipo_ids"]:
                    result["pending_ipos"].append(
                        {
                            "instrument_id": iid,
                            "model": model,
                            "origin_day": last["day"],
                            "expected_next_day": str(START),
                            "status": "pending",
                            "source": "baseline",
                        }
                    )
    atomic_json(target, result)
    return result


class Runtime:
    """真实执行边界；测试用 FakeRuntime 完全替换，不调用真实账户。"""

    def __init__(self, base: Path, *, lock_fd: int | None = None, account_env: str = ACCOUNT_ENV):
        require(bool(re.fullmatch(r"[A-Z][A-Z0-9_]*", account_env)), "invalid_account_env_name")
        self.account_env = account_env
        self._account_environment: Environment | None = None
        self.base = base
        self._quota_client = None
        self.pass_fds = () if lock_fd is None else (lock_fd,)

    def prepare_account(self) -> Environment:
        """冻结显式所选账号环境；密钥只在内存，不改变 YAML 或 variant。"""
        from gr_tools.config import Environment, load_environment

        if self._account_environment is None:
            source = load_environment(root=REPO)
            selected_key = source.values.get(self.account_env)
            require(
                isinstance(selected_key, str) and bool(selected_key.strip()),
                "selected_account_key_missing",
            )
            values = dict(source.values)
            values[ACCOUNT_ENV] = selected_key
            self._account_environment = Environment(source.root, values, source.env_file)
        return self._account_environment

    def check_version(self) -> str:
        # 新进程避开版本 helper 的进程内提交号缓存，检测运行中新增提交。
        probe = subprocess.run(
            [
                sys.executable,
                "-I",
                "-c",
                (
                    "from gr_data.db.risk_receipts import get_importer_version; "
                    "print(get_importer_version(require_clean=True))"
                ),
            ],
            cwd=REPO,
            capture_output=True,
            timeout=15,
            pass_fds=self.pass_fds,
        )
        require(probe.returncode == 0, "importer_not_clean_or_unavailable")
        return probe.stdout.decode().strip()

    def calendar(self) -> list[str]:
        import psycopg
        from gr_data.config import load_postgres, make_pg_dsn
        from gr_tools.config import load_environment

        env = load_environment(root=REPO)
        with psycopg.connect(make_pg_dsn(load_postgres(env))) as conn:
            conn.read_only = True
            with conn.cursor() as cursor:
                cursor.execute(
                    (
                        "SELECT trading_day FROM meta.trading_calendar "
                        "WHERE exchange=%s AND is_open "
                        "AND trading_day BETWEEN %s AND %s ORDER BY trading_day"
                    ),
                    ("XSHG", START, END),
                )
                result = [str(row[0]) for row in cursor.fetchall()]
            conn.rollback()
        snapshot_path = self.base / "calendar-crosscheck.json"
        require(snapshot_path.is_file(), "reviewed_calendar_missing")
        snapshot = json.loads(snapshot_path.read_text())
        require(
            snapshot.get("calendar_exchanges_equal") is True
            and snapshot.get("start_date") == str(START)
            and snapshot.get("end_date") == str(END)
            and snapshot.get("trading_days") == result,
            "calendar_changed_since_review",
        )
        return result

    def quota(self) -> dict:
        from gr_data.config.pipeline import load_config
        from gr_data.raw import _build_client
        from gr_data.raw.ricequant.riskmodel import _quota_snapshot

        if self._quota_client is None:
            cfg = load_config(
                self.base / "templates" / "v1.yaml", environment=self.prepare_account()
            )
            self._quota_client = _build_client("ricequant", cfg)
        return {**_quota_snapshot(self._quota_client), "account_env": self.account_env}

    def command(
        self, phase: str, config: Path, month: str, log: Path, *, observation_id: str | None = None
    ) -> int:
        args = [
            sys.executable,
            "-m",
            "gr_data.cli",
            "--config",
            str(config),
            phase,
            "ricequant",
            "--only",
            "rq_risk_model",
        ]
        args += ["--mode", "init"] if phase == "raw" else ["--months", month]
        if phase == "ingest" and observation_id is not None:
            args += ["--observation-id", observation_id]
        child_env = dict(self.prepare_account().values) if phase == "raw" else None
        with log.open("w") as output:
            # 超时/中断不自动重试；下次原生 init/receipt 重放确认最终状态。
            result = subprocess.run(
                args,
                cwd=REPO,
                stdout=output,
                stderr=subprocess.STDOUT,
                timeout=1800,
                pass_fds=self.pass_fds,
                env=child_env,
            )
        return result.returncode

    def bundle(self, config: Path, *, observation_id: str | None = None) -> tuple[dict, dict]:
        from gr_data.common.paths import RawPaths
        from gr_data.config.pipeline import load_config
        from gr_data.config.ricequant_risk import parse_risk_options
        from gr_data.raw.ricequant.riskmodel import read_bundles

        cfg = load_config(config)
        options = parse_risk_options(cfg.section("providers", "ricequant", "risk_model"))
        bundles = list(read_bundles(RawPaths(cfg.raw_root), options, observation_id=observation_id))
        return select_bundle(bundles, observation_id)

    def budget_failure(self, config: Path, started_at: str) -> bool:
        """仅接受当前尝试的明确类型收据；旧失败不能解释本轮认证等错误。"""
        from gr_data.common.paths import RawPaths
        from gr_data.config.pipeline import load_config
        from gr_data.config.ricequant_risk import parse_risk_options

        cfg = load_config(config)
        options = parse_risk_options(cfg.section("providers", "ricequant", "risk_model"))
        root = RawPaths(cfg.raw_root).ricequant_variant(
            "rq_risk_model", options.contract_version, options.variant_id
        )
        for path in (root / "_failed" / str(options.start_date)).glob("*/receipt.json"):
            receipt = json.loads(path.read_text())
            failure = receipt.get("failure", {})
            if (
                receipt.get("variant_id") == options.variant_id
                and failure.get("error_type") == "BudgetDeferredError"
                and datetime.fromisoformat(failure["failed_at"])
                >= datetime.fromisoformat(started_at)
            ):
                return True
        return False

    def audit(
        self,
        model: str,
        directory: Path,
        output_path: Path,
        log: Path,
        *,
        observation_id: str | None = None,
        importer_version: str | None = None,
    ) -> tuple[int, dict | None]:
        with log.open("w") as output:
            result = subprocess.run(
                [
                    sys.executable,
                    "-I",
                    str(self.base / "audit_monthly.py"),
                    "--models",
                    model,
                    "--config-dir",
                    str(directory),
                    "--output",
                    str(output_path),
                    "--skip-realized",
                    *(["--observation-id", observation_id] if observation_id else []),
                    *(["--importer-version", importer_version] if importer_version else []),
                ],
                cwd=REPO,
                stdout=output,
                stderr=subprocess.STDOUT,
                timeout=600,
                pass_fds=self.pass_fds,
            )
        report = json.loads(output_path.read_text()) if output_path.exists() else None
        return result.returncode, report


def quota_exhausted(snapshot: dict) -> bool:
    import math

    used, limit = snapshot.get("bytes_used"), snapshot.get("bytes_limit")
    require(
        type(used) in (int, float)
        and type(limit) in (int, float)
        and math.isfinite(used)
        and math.isfinite(limit)
        and used >= 0
        and limit > 0,
        "invalid_quota_snapshot",
    )
    return used >= limit * (1 - QUOTA_RESERVE)


def known_ipos(manifest: dict) -> list[dict]:
    gaps = [row for row in manifest["coverage"] if row["status"] != "included"]
    for row in gaps:
        evidence = row.get("evidence", {})
        require(
            row["status"] == "partial_bundle"
            and row["pieces"] == {"exposure": True, "specific_risk": True, "specific_return": False}
            and evidence.get("canonical", {}).get("list_date") == manifest["day"]
            and bool(evidence.get("supplier"))
            and all(item.get("listed_date") == manifest["day"] for item in evidence["supplier"]),
            "unreviewed_coverage_gap",
        )
    require(not manifest["universe"]["unresolved"], "unresolved_universe")
    return gaps


def evidence_digest(value: dict) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def load_version_policy(path: Path, ledger: dict) -> dict:
    """外部批准清单固定历史证据及唯一修复选择，不从当前 Git 自动采纳版本。"""
    policy = json.loads(path.read_text())
    require(policy.get("legacy_importer_version") == IMPORTER_VERSION, "unknown_legacy_version")
    current = policy.get("current_importer_version", "")
    require(
        bool(re.fullmatch(r"[0-9a-f]{40}", current)) and current != IMPORTER_VERSION,
        "invalid_current_version",
    )
    require(policy.get("schema_version") == 1, "unsupported_version_policy")
    frozen = policy["legacy_jobs"]
    for key, digest in frozen.items():
        require(
            key in ledger["jobs"] and evidence_digest(ledger["jobs"][key]) == digest,
            "legacy_job_evidence_changed",
        )
    for key, job in ledger["jobs"].items():
        if job.get("status") not in ("complete", "complete_degraded"):
            continue
        version = job.get(
            "importer_version", job.get("import_evidence", {}).get("importer_version")
        )
        require(version in (IMPORTER_VERSION, current), "unknown_job_version")
        require(version != IMPORTER_VERSION or key in frozen, "unfrozen_legacy_job")
    repair = policy["repair"]
    require(
        repair["key"] == "2024-12-11/v2"
        and repair["old_observation_id"] == "608016044ef54173a077abe5445c03b5"
        and repair["old_run_id"] == "4cc48d3d-663a-5fc9-be51-17548ec23966"
        and bool(re.fullmatch(r"[0-9a-f]{32}", repair["observation_id"]))
        and repair["observation_id"] != repair["old_observation_id"],
        "invalid_repair_selection",
    )
    require(
        evidence_digest(ledger["attempts"][: policy["legacy_attempt_count"]])
        == policy["legacy_attempts_sha256"],
        "legacy_attempt_evidence_changed",
    )
    pinned = ledger.get("version_policy_sha256")
    require(pinned is None or pinned == evidence_digest(policy), "version_policy_changed")
    return policy


def select_bundle(bundles: list, observation_id: str | None) -> tuple[dict, dict]:
    selected = [
        item
        for item in bundles
        if observation_id is None or item[0]["observation_id"] == observation_id
    ]
    require(len(selected) == 1, "explicit_observation_required_or_missing")
    return selected[0]


class Runner:
    def __init__(
        self,
        base: Path,
        runtime: Any,
        templates: dict,
        variants: dict,
        baseline: dict,
        policy: dict | None = None,
    ):
        self.policy = policy
        self.current_version = policy["current_importer_version"] if policy else IMPORTER_VERSION
        self.base, self.runtime, self.templates, self.variants = base, runtime, templates, variants
        self.account_env = getattr(runtime, "account_env", ACCOUNT_ENV)
        self.ledger_path = base / "ledger.json"
        self.baseline = baseline
        if self.ledger_path.exists():
            self.ledger = json.loads(self.ledger_path.read_text())
            require(
                self.ledger["range"] == {"start": str(START), "end": str(END)}
                and self.ledger["importer_version"] == IMPORTER_VERSION
                and self.ledger["variants"] == variants
                and self.ledger["account_env"] == ACCOUNT_ENV,
                "ledger_identity_changed",
            )
        else:
            self.ledger = {
                "schema_version": 1,
                "range": {"start": str(START), "end": str(END)},
                "importer_version": IMPORTER_VERSION,
                "variants": variants,
                "account_env": ACCOUNT_ENV,
                "created_at": now(),
                "calendar": [],
                "jobs": {},
                "attempts": [],
                "pending_ipos": list(baseline.get("pending_ipos", [])),
                "status": "initialized",
            }

        if policy:
            require(
                evidence_digest(baseline) == policy["baseline_sha256"], "baseline_evidence_changed"
            )
            self.ledger["version_policy_sha256"] = evidence_digest(policy)

    def save(self) -> None:
        self.ledger["updated_at"] = now()
        atomic_json(self.ledger_path, self.ledger)

    def reports(self) -> None:
        for month in sorted(
            {job["day"][:7] for job in self.ledger["jobs"].values()}
            | {job["day"][:7] for job in self.baseline.get("jobs", [])}
        ):
            jobs = [job for job in self.ledger["jobs"].values() if job["day"].startswith(month)]
            baseline = [
                job for job in self.baseline.get("jobs", []) if job["day"].startswith(month)
            ]
            attempts = [
                attempt for attempt in self.ledger["attempts"] if attempt["day"].startswith(month)
            ]
            planned = [
                f"{day}/{model}"
                for day in self.ledger["calendar"]
                if day.startswith(month)
                for model in MODELS
            ]
            complete = [job for job in jobs if job["status"] in ("complete", "complete_degraded")]
            pending = [
                row
                for row in self.ledger["pending_ipos"]
                if row["origin_day"].startswith(month) and row["status"] == "pending"
            ]
            quota_samples = [
                {
                    **attempt[key],
                    "account_env": attempt[key].get(
                        "account_env", attempt.get("account_env", ACCOUNT_ENV)
                    ),
                }
                for attempt in attempts
                for key in ("quota_before", "quota_after")
                if key in attempt
            ]
            start, end = (quota_samples[0], quota_samples[-1]) if quota_samples else (None, None)
            observed_days = {}
            for sample in quota_samples:
                stamp = datetime.fromisoformat(sample["observed_at"])
                key = stamp.astimezone(ZoneInfo("Asia/Shanghai")).date().isoformat()
                observed_days.setdefault((sample["account_env"], key), []).append(sample)
            quota_days = []
            for (account_env, observed_day), samples in sorted(observed_days.items()):
                first, last = samples[0], samples[-1]
                delta = last["bytes_used"] - first["bytes_used"]
                reset = any(
                    right["bytes_used"] < left["bytes_used"]
                    for left, right in zip(samples, samples[1:], strict=False)
                )
                quota_days.append(
                    {
                        "observation_day": observed_day,
                        "account_env": account_env,
                        "first": first,
                        "last": last,
                        "observed_delta_bytes": delta if not reset and delta >= 0 else None,
                        "reset_or_unknown": reset or delta < 0,
                    }
                )
            report = {
                "month": month,
                "fixed_range": self.ledger["range"],
                "legacy_importer_version": IMPORTER_VERSION,
                "active_importer_version": self.current_version,
                "importer_versions": sorted(
                    {
                        job.get(
                            "importer_version",
                            job.get("import_evidence", {}).get(
                                "importer_version", IMPORTER_VERSION
                            ),
                        )
                        for job in complete + baseline
                    }
                ),
                "new_complete_model_days": len(complete),
                "new_planned_model_days": len(planned),
                "new_ingestion_complete": bool(planned) and len(complete) == len(planned),
                "baseline_model_days": len(baseline),
                "baseline_note": (
                    "Previously audited evidence; not recaptured or live-reverified by this runner."
                ),
                "coverage": [
                    dict(
                        day=job["day"],
                        model=job["model"],
                        importer_version=job.get(
                            "importer_version",
                            job.get("import_evidence", {}).get(
                                "importer_version", IMPORTER_VERSION
                            ),
                        ),
                        counts=job.get("coverage_counts"),
                        status=job["status"],
                    )
                    for job in [*baseline, *jobs]
                ],
                "ipo_origin_count": sum(
                    len(job.get("known_ipo_ids", [])) for job in [*baseline, *complete]
                ),
                "ipo_unique_instrument_count": len(
                    {iid for job in [*baseline, *complete] for iid in job.get("known_ipo_ids", [])}
                ),
                "ipo_origin_dates": sorted(
                    {job["day"] for job in [*baseline, *complete] if job.get("known_ipo_ids")}
                ),
                "ipo_next_day_pending": pending,
                "below_99_9_model_days": [
                    dict(day=job["day"], model=job["model"])
                    for job in complete
                    if not job["publication_eligible"]
                ],
                "receipts_and_checkpoints": [
                    dict(day=job["day"], model=job["model"], evidence=job["import_evidence"])
                    for job in [*baseline, *complete]
                ],
                "attempt_count": len(attempts),
                "failed_or_interrupted_attempts": [
                    a for a in attempts if a["status"] not in ("complete", "complete_degraded")
                ],
                "quota": {
                    "before": start,
                    "after": end,
                    "by_observation_day": quota_days,
                    "observed_nonnegative_delta_sum_bytes": sum(
                        row["observed_delta_bytes"] or 0 for row in quota_days
                    ),
                    "note": QUOTA_NOTE
                    + (
                        " Daily boundary changes are not assigned across observation days; "
                        "missing reset intervals are unknown."
                    ),
                },
                "validation_complete": bool(planned)
                and len(complete) == len(planned)
                and not pending,
                "official_read_enabled": False,
                "reported_at": now(),
            }
            atomic_json(self.base / "reports" / f"{month}.json", report)
            text = (
                f"# 米筐回补 {month}\n\n新完成模型日：{len(complete)}/{len(planned)}；"
                f"既有验收模型日：{len(baseline)}。\n\n"
            )
            text += (
                f"IPO 首日缺口：{report['ipo_origin_count']}；下一交易日待核实：{len(pending)}；"
                f"完整率低于 99.9% 的模型日：{len(report['below_99_9_model_days'])}。\n\n"
            )
            text += "数据保持原用途、覆盖与发布资格；本报告不开放正式风险数据读取。\n\n"
            text += "|日期|模型|候选|完整|状态|\n|---|---|---:|---:|---|\n"
            for row in report["coverage"]:
                counts = row["counts"] or {}
                text += (
                    f"|{row['day']}|{row['model']}|{counts.get('candidate', '')}|"
                    f"{counts.get('complete', '')}|{row['status']}|\n"
                )
            text += (
                "\n流量仅为账户计数观测；可能延迟、跨日重置或包含其他调用。观测差值："
                f"{report['quota']['observed_nonnegative_delta_sum_bytes']} bytes；"
                "零差值不代表零流量。完整 receipt、双水位和所有尝试见同名 JSON。\n"
            )
            atomic_text(self.base / "reports" / f"{month}.md", text)

    def run(self, through: date, *, resume_after_review: str | None = None) -> int:
        require(START <= through <= END, "run_range_outside_fixed_bounds")
        require(self.runtime.check_version() == self.current_version, "importer_version_changed")
        require(
            resume_after_review is None or 0 < len(resume_after_review.strip()) <= 240,
            "invalid_review_reason",
        )
        interrupted = [
            attempt for attempt in self.ledger["attempts"] if attempt["status"] == "running"
        ]
        if interrupted:
            for attempt in interrupted:
                attempt.update(status="interrupted", interrupted_at=now())
            self.ledger.update(
                status="needs_attention",
                last_stop={"reason": "interrupted_attempt_requires_review", "at": now()},
            )
            self.save()
        if self.ledger.get("status") in ("needs_attention", "stopped_for_review"):
            if not resume_after_review:
                self.save()
                self.reports()
                return 1
            self.ledger.setdefault("review_acknowledgments", []).append(
                {
                    "at": now(),
                    "reason": resume_after_review,
                    "previous_stop": self.ledger.get("last_stop"),
                }
            )
        quota_stops = self.ledger.setdefault("quota_stops", {})
        legacy_stop = self.ledger.get("quota_stop")
        if legacy_stop:
            quota_stops.setdefault(legacy_stop.get("account_env", ACCOUNT_ENV), legacy_stop)
        if quota_stops.get(self.account_env, {}).get("local_day") == local_day():
            self.ledger["status"] = "budget_deferred"
            self.save()
            self.reports()
            return 2
        if not self.ledger["calendar"]:
            days = self.runtime.calendar()
            require(
                days == sorted(set(days))
                and bool(days)
                and days[0] == str(START)
                and days[-1] == str(END)
                and all(START <= date.fromisoformat(day) <= END for day in days),
                "calendar_incomplete_or_invalid",
            )
            self.ledger["calendar"] = days
        self.ledger["status"] = "running"
        self.ledger["active_account_env"] = self.account_env
        self.save()
        try:
            for day in self.ledger["calendar"]:
                if date.fromisoformat(day) > through:
                    break
                for model in MODELS:
                    key = f"{day}/{model}"
                    if self.ledger["jobs"].get(key, {}).get("status") in (
                        "complete",
                        "complete_degraded",
                    ):
                        continue
                    self.run_job(day, model)
            self.ledger["status"] = "through_month_completed" if through < END else "completed"
            if through == END and any(
                row["status"] == "pending" for row in self.ledger["pending_ipos"]
            ):
                self.ledger["status"] = "needs_attention"
                self.ledger["last_stop"] = {
                    "reason": "terminal_ipo_recovery_unconfirmed",
                    "at": now(),
                }
            self.ledger["completed_through"] = str(through)
            self.save()
            self.reports()
            return 1 if self.ledger["status"] == "needs_attention" else 0
        except Exception as exc:
            quota = (
                isinstance(exc, StopRunError)
                and exc.quota
                or type(exc).__name__ == "BudgetDeferredError"
            )
            reason = exc.reason if isinstance(exc, StopRunError) else type(exc).__name__
            self.ledger["status"] = "budget_deferred" if quota else "needs_attention"
            self.ledger["last_stop"] = {
                "reason": reason,
                "at": now(),
                "job": self.ledger.get("active_job"),
            }
            if quota:
                self.ledger["quota_stop"] = {
                    "local_day": local_day(),
                    "account_env": self.account_env,
                    "reason": reason,
                    "resume_not_before_local_day": str(
                        date.fromisoformat(local_day()) + timedelta(days=1)
                    ),
                }
            if quota:
                self.ledger["quota_stops"][self.account_env] = self.ledger["quota_stop"]
            self.save()
            self.reports()
            return 2 if quota else 1

    def run_job(self, day: str, model: str) -> None:
        key = f"{day}/{model}"
        repair = (
            self.policy["repair"] if self.policy and self.policy["repair"]["key"] == key else None
        )
        selected_id = repair["observation_id"] if repair else None
        directory = self.base / "days" / day
        directory.mkdir(parents=True, exist_ok=True)
        data = yaml.safe_load(yaml.safe_dump(self.templates[model]))
        data["providers"]["ricequant"]["risk_model"].update(start_date=day, end_date=day)
        from gr_data.config.ricequant_risk import parse_risk_options

        require(
            parse_risk_options(data["providers"]["ricequant"]["risk_model"]).variant_id
            == self.variants[model],
            "daily_config_changed_variant",
        )
        config = directory / f"{model}.yaml"
        atomic_text(config, yaml.safe_dump(data, allow_unicode=True, sort_keys=False))
        attempt = {
            "importer_version": self.current_version,
            "attempt_id": uuid4().hex,
            "account_env": self.account_env,
            "day": day,
            "model": model,
            "status": "running",
            "started_at": now(),
            "stage": "quota_before",
        }
        self.ledger["attempts"].append(attempt)
        self.ledger["active_job"] = {
            "day": day,
            "model": model,
            "attempt_id": attempt["attempt_id"],
        }
        self.ledger["jobs"].setdefault(key, {"day": day, "model": model, "status": "pending"})
        self.save()
        prefix = f"{model}-{attempt['attempt_id']}"
        try:
            require(
                self.runtime.check_version() == self.current_version, "importer_version_changed"
            )
            attempt["quota_before"] = {**self.runtime.quota(), "account_env": self.account_env}
            self.save()
            if quota_exhausted(attempt["quota_before"]):
                raise StopRunError("quota_reserve_reached_before_job", quota=True)
            attempt.update(stage="raw", raw_started_at=now())
            self.save()
            require(
                self.runtime.check_version() == self.current_version, "importer_version_changed"
            )
            attempt["raw_exit"] = self.runtime.command(
                "raw", config, day[:7], directory / f"{prefix}-raw.log"
            )
            try:
                attempt["quota_after"] = {**self.runtime.quota(), "account_env": self.account_env}
            except Exception as quota_error:
                attempt["quota_after_error_type"] = type(quota_error).__name__
                if attempt["raw_exit"] == 0:
                    raise
            self.save()
            if attempt["raw_exit"]:
                # after 计数上涨或配额查询失败不得覆盖实际原始请求的非预算错误。
                deferred = self.runtime.budget_failure(config, attempt["raw_started_at"])
                raise StopRunError(
                    "raw_budget_deferred" if deferred else "raw_failed_unclassified", quota=deferred
                )
            manifest, _ = self.runtime.bundle(
                config, **({"observation_id": selected_id} if selected_id else {})
            )
            require(
                manifest["day"] == day
                and manifest["variant_id"] == self.variants[model]
                and manifest["purpose"] == "production",
                "raw_identity_mismatch",
            )
            gaps = known_ipos(manifest)
            attempt.update(
                stage="coverage",
                coverage_counts=manifest["coverage_counts"],
                observation_id=manifest["observation_id"],
            )
            included_ids = {
                row["instrument_id"] for row in manifest["coverage"] if row["status"] == "included"
            }
            due = [
                row
                for row in self.ledger["pending_ipos"]
                if row["model"] == model
                and row["status"] == "pending"
                and row.get("expected_next_day") is not None
                and row["expected_next_day"] <= day
            ]
            require(
                all(
                    row["expected_next_day"] == day and row["instrument_id"] in included_ids
                    for row in due
                ),
                "ipo_not_recovered_next_trading_day",
            )
            special = self.special_check(day, model, manifest)
            attempt["special_checks"] = special
            attempt["stage"] = "ingest"
            self.save()
            require(
                self.runtime.check_version() == self.current_version, "importer_version_changed"
            )
            attempt["ingest_exit"] = self.runtime.command(
                "ingest",
                config,
                day[:7],
                directory / f"{prefix}-ingest.log",
                **({"observation_id": manifest["observation_id"]} if self.policy else {}),
            )
            self.save()
            require(attempt["ingest_exit"] in (0, 4), "ingest_exit_requires_review")
            attempt["stage"] = "audit"
            output = directory / f"{prefix}-audit.json"
            self.save()
            require(
                self.runtime.check_version() == self.current_version, "importer_version_changed"
            )
            code, report = self.runtime.audit(
                model,
                directory,
                output,
                directory / f"{prefix}-audit.log",
                **(
                    {
                        "observation_id": manifest["observation_id"],
                        "importer_version": self.current_version,
                    }
                    if self.policy
                    else {}
                ),
            )
            attempt["audit_exit"] = code
            require(
                code == 0
                and report is not None
                and report.get("status") == "passed"
                and len(report.get("models", [])) == 1,
                "independent_audit_failed",
            )
            audit = report["models"][0]
            require(
                audit.get("status") == "passed"
                and audit["model"] == model
                and audit["trading_day"] == day
                and audit["variant_id"] == self.variants[model]
                and audit["observation_id"] == manifest["observation_id"],
                "audit_identity_mismatch",
            )
            require(
                audit.get("continuation_allowed") is True
                and sorted(audit.get("next_day_pending_instrument_ids", []))
                == sorted(row["instrument_id"] for row in gaps),
                "audit_ipo_continuation_mismatch",
            )
            evidence = audit["import_evidence"]
            require(
                evidence["status"] == "passed"
                and evidence["importer_version"] == self.current_version,
                "audit_receipt_version",
            )
            gate = evidence["publication_gate"]
            counts = manifest["coverage_counts"]
            below = counts["complete"] * 1000 < counts["candidate"] * 999
            require(audit["coverage_counts"] == counts, "audit_coverage_mismatch")
            if attempt["ingest_exit"] == 4:
                require(
                    bool(gaps)
                    and below
                    and gate["eligible"] is False
                    and gate["reasons"] == ["complete_coverage_below_99_9_percent"],
                    "exit4_not_only_known_ipo_coverage",
                )
            else:
                require(
                    gate["eligible"] is True and not below and gate["reasons"] == [],
                    "success_exit_publication_mismatch",
                )
            require(
                not audit["quality"].get("warnings")
                and not audit["quality"]["covariance"].get("warnings")
                and all(n == int(bool(gaps)) for n in audit["etl_warning_counts"]),
                "numeric_or_unexpected_etl_warning",
            )
            next_index = self.ledger["calendar"].index(day) + 1
            next_day = (
                self.ledger["calendar"][next_index]
                if next_index < len(self.ledger["calendar"])
                else None
            )
            for row in due:
                row.update(
                    status="confirmed",
                    confirmed_day=day,
                    confirmed_observation_id=manifest["observation_id"],
                )
            for gap in gaps:
                self.ledger["pending_ipos"].append(
                    {
                        "instrument_id": gap["instrument_id"],
                        "canonical_symbol": gap["canonical_symbol"],
                        "model": model,
                        "origin_day": day,
                        "expected_next_day": next_day,
                        "status": "pending",
                    }
                )
            status = "complete_degraded" if not gate["eligible"] else "complete"
            attempt.update(
                status=status,
                stage="complete",
                finished_at=now(),
                audit_path=str(output.relative_to(self.base)),
            )
            self.ledger["jobs"][key] = {
                "importer_version": self.current_version,
                "day": day,
                "model": model,
                "status": status,
                "coverage_counts": counts,
                "publication_eligible": gate["eligible"],
                "known_ipo_ids": [row["instrument_id"] for row in gaps],
                "observation_id": manifest["observation_id"],
                "run_id": audit["run_id"],
                "import_evidence": evidence,
                "special_checks": {**special, "audit": audit.get("special_checks")},
                "attempt_id": attempt["attempt_id"],
                "audit_path": attempt["audit_path"],
            }
            if repair:
                self.ledger.setdefault("supersessions", []).append(
                    {
                        **repair,
                        "new_run_id": audit["run_id"],
                        "importer_version": self.current_version,
                        "accepted_at": now(),
                        "new_attempt_id": attempt["attempt_id"],
                    }
                )
            self.ledger["active_job"] = None
            self.save()
            self.reports()
            print(
                json.dumps(
                    {
                        "status": status,
                        "day": day,
                        "model": model,
                        "coverage_counts": counts,
                        "ipo_pending": len(gaps),
                    },
                    ensure_ascii=False,
                ),
                flush=True,
            )
        except Exception as exc:
            attempt.update(
                status="quota_deferred"
                if isinstance(exc, StopRunError)
                and exc.quota
                or type(exc).__name__ == "BudgetDeferredError"
                else "failed",
                error_type=type(exc).__name__,
                reason=exc.reason
                if isinstance(exc, StopRunError)
                else "external_error_details_suppressed",
                finished_at=now(),
            )
            self.save()
            raise

    def special_check(self, day: str, model: str, manifest: dict) -> dict:
        result = {}
        if day in ("2025-02-14", "2025-02-17"):
            expected = "300114.XSHE" if day == "2025-02-14" else "302132.XSHE"
            rows = [row for row in manifest["coverage"] if row["request_code"] == expected]
            require(
                len(rows) == 1 and rows[0]["status"] == "included",
                "historical_alias_request_or_coverage",
            )
            iid = rows[0]["instrument_id"]
            if day == "2025-02-17":
                prior = self.ledger["jobs"].get(f"2025-02-14/{model}", {}).get("special_checks", {})
                require(
                    prior.get("alias_instrument_id") == iid, "historical_alias_identity_changed"
                )
            for other_model in MODELS:
                peer = self.ledger["jobs"].get(f"{day}/{other_model}", {}).get("special_checks", {})
                require(
                    peer.get("alias_instrument_id", iid) == iid, "historical_alias_models_disagree"
                )
            result.update(alias_request_code=expected, alias_instrument_id=iid, alias_covered=True)
        if day == str(END):
            rows = [row for row in manifest["coverage"] if row["canonical_symbol"] == "000016.SZ"]
            require(len(rows) == 1, "halted_stock_missing_from_terminal_universe")
            result.update(
                halted_000016_candidate=True,
                halted_000016_instrument_id=rows[0]["instrument_id"],
                halted_000016_coverage_status=rows[0]["status"],
            )
        return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--account-env",
        default=ACCOUNT_ENV,
        help="Explicit credential environment variable; no automatic rotation",
    )
    parser.add_argument("--version-policy", type=Path, default=BASE / "version-policy.json")
    parser.add_argument("--through-month", help="Inclusive month, bounded by 2024-01 and 2026-10")
    parser.add_argument(
        "--resume-after-review",
        metavar="REASON",
        help="Manual reviewed recovery only; never set from automation; do not include credentials",
    )
    parser.add_argument(
        "--validate-only",
        action="store_true",
        help="Offline template, identity and clean importer checks only",
    )
    args = parser.parse_args()
    BASE.mkdir(parents=True, exist_ok=True)
    try:
        with (BASE / ".runner.lock").open("a") as lock:
            try:
                fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise StopRunError("runner_already_active") from None
            through = month_limit(args.through_month)
            runtime = Runtime(BASE, lock_fd=lock.fileno(), account_env=args.account_env)
            policy = load_version_policy(
                args.version_policy, json.loads((BASE / "ledger.json").read_text())
            )
            require(
                runtime.check_version() == policy["current_importer_version"],
                "importer_version_changed",
            )
            templates, variants = load_templates(BASE)
            baseline = json.loads((BASE / "baseline.json").read_text())
            require(
                evidence_digest(baseline) == policy["baseline_sha256"], "baseline_evidence_changed"
            )
            if args.validate_only:
                print(
                    json.dumps(
                        {
                            "status": "validation_passed",
                            "range": {"start": str(START), "end": str(END)},
                            "selected_through": str(through),
                            "variants": variants,
                            "importer_version": policy["current_importer_version"],
                            "account_env": args.account_env,
                            "network_or_database_used": False,
                        }
                    )
                )
                return 0
            runtime.prepare_account()
            require((BASE / "audit_monthly.py").is_file(), "audit_script_missing")
            runner = Runner(BASE, runtime, templates, variants, baseline, policy=policy)
            code = runner.run(through, resume_after_review=args.resume_after_review)
            print(
                json.dumps(
                    {
                        "status": runner.ledger["status"],
                        "exit_code": code,
                        "stop": runner.ledger.get("last_stop"),
                    },
                    ensure_ascii=False,
                )
            )
            return code
    except Exception as exc:
        print(
            json.dumps(
                {
                    "status": "stopped",
                    "error_type": type(exc).__name__,
                    "reason": exc.reason
                    if isinstance(exc, StopRunError)
                    else "external_error_details_suppressed",
                }
            ),
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
