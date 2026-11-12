"""D-026 按用途准入；当前快照不构成历史合约参数。"""

from __future__ import annotations

from gr_data.ingest.base import IngestGateError


QUOTE_SNAPSHOT_ADMISSION = "quote_history_current_snapshot_v1"
ADMITTED_USES = frozenset({"quote_history", "current_contract_snapshot"})
ADMITTED_DATASETS = frozenset(
    {"option_instruments", "option_symbol_map", "option_contracts", "option_bar_1d"}
)


def require_option_admission(dataset: str, *, validation_only: bool, admission: str | None) -> None:
    """在归属登记和写库前校验显式用途，保留原隔离验证入口。

    Args:
        dataset: 四个既有期权 writer 之一。
        validation_only: 仅供隔离验证的原开关。
        admission: 显式批准的报价历史／当前快照用途；默认不开放。

    Raises:
        IngestGateError: 未批准、未知用途，或混用正式与隔离开关。
    """
    if validation_only and admission is not None:
        raise IngestGateError("Option validation and purpose admission cannot be combined")
    if admission is not None and (
        admission != QUOTE_SNAPSHOT_ADMISSION or dataset not in ADMITTED_DATASETS
    ):
        raise IngestGateError(
            f"Unapproved option admission dataset={dataset} admission={admission}"
        )
    if validation_only is not True and admission != QUOTE_SNAPSHOT_ADMISSION:
        raise IngestGateError(
            "Option writes are validation-only unless quote history/current snapshot "
            "purpose admission is explicit; historical contract parameters are not verified"
        )


def require_option_use(use: str) -> None:
    """拒绝以本批准入证明历史参数、历史收益、模型指标或交易资格。

    准入只说明可读取源报价和当前观察；不自动授权定价或交易。
    """
    if use not in ADMITTED_USES:
        raise IngestGateError(f"Option use is not admitted by quote/snapshot evidence: {use}")
