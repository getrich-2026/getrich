"""米筐补充任务准入与选择；先校验全批，再允许产生外部副作用。"""

from __future__ import annotations

import math
import os
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from gr_data.common.ricequant_specs import (
    CONDITIONAL_DATASETS,
    DAILY_FIELDS,
    DEFINITION_VERSION,
    GROUPS,
    INDEX_DEFINITIONS,
    INDEX_SPECS,
    RqConfigurationError,
    semantic_hash,
)
from gr_data.config.pipeline import Config
from gr_data.config.ricequant_risk import RiskOptions, parse_risk_options


def _date(value: object) -> date:
    try:
        return date.fromisoformat(str(value))
    except (ValueError, TypeError):
        raise RqConfigurationError("米筐补充任务必须填写合法起止日期") from None


def _names(value: object, label: str) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)) or any(not isinstance(v, str) or not v for v in value):
        raise RqConfigurationError(f"{label} 必须是非空字符串组成的列表")
    if len(set(value)) != len(value):
        raise RqConfigurationError(f"{label} 不能重复")
    return tuple(value)


@dataclass(frozen=True)
class DatasetOptions:
    name: str
    contract_version: str
    start_date: date
    end_date: date
    index_codes: tuple[str, ...]
    fields: tuple[str, ...]
    evidence: dict[str, object]
    enable_bjse: bool = False
    replay_trading_days: int = 5
    max_symbols_per_request: int = 10
    max_pending_bytes: int = 67108864

    @property
    def variant_id(self) -> str:
        """语义身份不含日期、代码清单或分片大小。"""
        return semantic_hash(
            {
                "dataset": self.name,
                "contract_version": self.contract_version,
                "fields": sorted(self.fields),
                "frequency": "1d",
                "adjust_type": "none",
                "definition_version": DEFINITION_VERSION,
                "availability": "observed",
                "raw_units": "provider_native",
                "enable_bjse": self.enable_bjse,
            }
        )

    @property
    def evidence_hash(self) -> str:
        return semantic_hash(self.evidence)


@dataclass(frozen=True)
class RicequantImportOptions:
    datasets: dict[str, DatasetOptions | RiskOptions]
    quota_reserve_fraction: float = 0.1
    license_key: str = field(default="", repr=False)
    connect_timeout: float = 5
    timeout: float = 60


_DATASET_KEYS = {
    "selected",
    "contract_version",
    "start_date",
    "end_date",
    "index_codes",
    "fields",
    "evidence",
    "replay_trading_days",
    "max_symbols_per_request",
    "max_pending_bytes",
    "enable_bjse",
}
_EVIDENCE_KEYS = {
    "tushare_overlap",
    "datayes_overlap",
    "rq_permission",
    "contract_status",
    "references",
    "checked_on",
}


def _dataset(name: str, data: dict[str, Any]) -> DatasetOptions:
    version = data.get("contract_version", "v1")
    if version != "v1":
        raise RqConfigurationError(f"{name} 尚未实现此契约版本")
    start, end = _date(data.get("start_date")), _date(data.get("end_date"))
    if start > end:
        raise RqConfigurationError(f"{name} 起止日期倒置")
    codes = _names(data.get("index_codes"), "index_codes")
    if not codes or not set(codes) <= INDEX_DEFINITIONS.keys():
        raise RqConfigurationError(f"{name} 必须使用已定义的首期 .RI 白名单")
    fields = _names(
        data.get("fields", list(DAILY_FIELDS) if name == "rq_index_daily" else []), "fields"
    )
    if name == "rq_index_daily":
        if "close" not in fields or not set(fields) <= set(DAILY_FIELDS):
            raise RqConfigurationError("指数日值字段必须包含 close 且在字段白名单中")
    elif fields:
        raise RqConfigurationError("成分／权重接口不接受 fields 参数")
    enable_bjse = data.get("enable_bjse", False)
    if type(enable_bjse) is not bool:
        raise RqConfigurationError("enable_bjse 必须为布尔值")
    if name != "rq_index_daily" and "enable_bjse" not in data:
        raise RqConfigurationError(
            "成员接口必须经样本核对后显式声明 enable_bjse，防止 SDK 静默过滤北交所"
        )
    evidence = data.get("evidence", {})
    if not isinstance(evidence, dict) or set(evidence) - _EVIDENCE_KEYS:
        raise RqConfigurationError(f"{name} 准入证据字段错误")
    expected = {
        "tushare_overlap": "distinct",
        "datayes_overlap": "distinct",
        "rq_permission": "confirmed",
        "contract_status": "verified",
    }
    if any(evidence.get(k) != v for k, v in expected.items()):
        raise RqConfigurationError(f"{name} 尚未通过去重／权限／契约准入")
    references = _names(evidence.get("references"), "evidence.references")
    if not references:
        raise RqConfigurationError(f"{name} 缺少证据引用")
    _date(evidence.get("checked_on"))
    evidence = dict(evidence, checked_on=str(evidence["checked_on"]), references=list(references))
    limits = {}
    for key, default in (
        ("replay_trading_days", 5),
        ("max_symbols_per_request", 10),
        ("max_pending_bytes", 67108864),
    ):
        val = data.get(key, default)
        if type(val) is not int or val <= 0:
            raise RqConfigurationError(f"{name}.{key} 必须是正整数")
        limits[key] = val
    return DatasetOptions(
        name,
        version,
        start,
        end,
        tuple(sorted(codes)),
        fields,
        evidence,
        enable_bjse=enable_bjse,
        **limits,
    )


def parse_ricequant_options(cfg: Config, *, phase: str) -> RicequantImportOptions:
    """解析显式快照；离线 ingest 不要求凭证或联网开关。"""
    if phase not in {"raw", "ingest"}:
        raise RqConfigurationError("未知米筐执行阶段")
    section = cfg.section("providers", "ricequant")
    supplements = section.get("supplements", {})
    if not isinstance(supplements, dict) or set(supplements) - {
        "datasets",
        "quota_reserve_fraction",
    }:
        raise RqConfigurationError("米筐 supplements 配置字段错误")
    entries = supplements.get("datasets", {})
    if not isinstance(entries, dict):
        raise RqConfigurationError("米筐 datasets 必须为映射")
    datasets = {}
    for name, data in entries.items():
        if name not in INDEX_SPECS and name not in CONDITIONAL_DATASETS:
            raise RqConfigurationError("未知米筐补充数据集")
        if not isinstance(data, dict) or type(data.get("selected", False)) is not bool:
            raise RqConfigurationError(f"{name}.selected 必须为布尔值")
        if name in CONDITIONAL_DATASETS:
            if data.get("selected"):
                raise RqConfigurationError(f"{name} 为尚未实现的条件候选")
            continue
        if set(data) - _DATASET_KEYS:
            raise RqConfigurationError(f"{name} 含未知配置字段")
        if data.get("selected"):
            datasets[name] = _dataset(name, data)
    risk = section.get("risk_model", {})
    if not isinstance(risk, dict) or type(risk.get("selected", False)) is not bool:
        raise RqConfigurationError("risk_model.selected 必须为布尔值")
    if risk.get("selected"):
        datasets["rq_risk_model"] = parse_risk_options(risk)
    reserve = supplements.get("quota_reserve_fraction", 0.1)
    if not isinstance(reserve, (int, float)) or not math.isfinite(reserve) or not 0 <= reserve < 1:
        raise RqConfigurationError("quota_reserve_fraction 必须在 [0,1) 内")
    values = cfg.environment.values if cfg.environment is not None else os.environ
    key_env = section.get("license_env", "RICEQUANT_API_KEY")
    license_key = values.get(key_env, "") if isinstance(key_env, str) else ""
    if phase == "raw" and datasets:
        if values.get("RICEQUANT_ENABLED", "").strip().lower() not in {"true", "1", "yes"}:
            raise RqConfigurationError("米筐补充采集需要 RICEQUANT_ENABLED=true")
        if not license_key.strip():
            raise RqConfigurationError("米筐补充采集缺少 RICEQUANT_API_KEY")
    timeouts = {}
    for key, default in (("connect_timeout", 5), ("timeout", 60)):
        value = section.get(key, default)
        if not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
            raise RqConfigurationError(f"{key} 必须是有限正数")
        timeouts[key] = float(value)
    rate = section.get("rate_limit", {})
    if not isinstance(rate, dict):
        raise RqConfigurationError("米筐 rate_limit 必须为映射")
    attempts = rate.get("max_retries", 5)
    if type(attempts) is not int or not 1 <= attempts <= 20:
        raise RqConfigurationError("米筐 max_retries 必须为 1–20 的整数")
    for key, default in (("sleep_between_requests_sec", 1.5), ("retry_backoff_base_sec", 3.0)):
        value = rate.get(key, default)
        if type(value) not in {int, float} or not math.isfinite(value) or value < 0:
            raise RqConfigurationError(f"米筐 {key} 必须是非负有限数")
    return RicequantImportOptions(datasets, float(reserve), license_key, **timeouts)


def select_datasets(
    requested: list[str] | None,
    cfg: Config,
    *,
    phase: str,
    legacy: tuple[str, ...],
    legacy_groups: dict[str, list[str]] | None = None,
) -> tuple[tuple[str, ...], RicequantImportOptions]:
    """全批展开与校验，显式空列表不回落；all 仅包含旧任务。"""
    names = (
        requested
        if requested is not None
        else cfg.get("enabled", phase, "ricequant", default=list(legacy))
    )
    names = _names(names, "enabled.ricequant")
    expanded = []
    for name in names:
        if name == "all":
            expanded.extend(legacy)
        elif name in GROUPS:
            expanded.extend(GROUPS[name])
        elif legacy_groups and name in legacy_groups:
            expanded.extend(legacy_groups[name])
        else:
            expanded.append(name)
    expanded = list(dict.fromkeys(expanded))
    # 旧任务不受补充数据配置和网络开关影响；但任何未知名称都先拒绝。
    if any(
        n not in {*legacy, *INDEX_SPECS, *CONDITIONAL_DATASETS, "rq_risk_model"} for n in expanded
    ):
        raise RqConfigurationError("未知米筐任务，未执行任何采集或入库")
    options = (
        parse_ricequant_options(cfg, phase=phase)
        if any(n not in legacy for n in expanded)
        else RicequantImportOptions({})
    )
    for name in expanded:
        if name in CONDITIONAL_DATASETS:
            raise RqConfigurationError(f"{name} 为尚未实现的条件候选")
        if name in {*INDEX_SPECS, "rq_risk_model"} and name not in options.datasets:
            raise RqConfigurationError(f"{name} 未选定或未通过准入")
    return tuple(expanded), options
