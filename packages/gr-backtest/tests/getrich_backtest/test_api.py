import getrich_backtest
from getrich_backtest import (
    Backtest,
    BacktestResult,
    BarSchemaError,
    DataFrameBarLoader,
    Fill,
    NextBarMatchingModel,
    Order,
    OrderIntent,
    OrderStatus,
    Side,
    Strategy,
    get_shanghai_tz,
    validate_bar_schema,
)


def test_package_exports_version() -> None:
    assert getrich_backtest.__version__ == "0.2.0"


def test_public_api_exports_core_types() -> None:
    assert Backtest.__name__ == "Backtest"
    assert Strategy.__name__ == "Strategy"


def test_public_api_exports_p0_foundation() -> None:
    assert BarSchemaError.__name__ == "BarSchemaError"
    assert DataFrameBarLoader.__name__ == "DataFrameBarLoader"
    assert OrderIntent.__name__ == "OrderIntent"
    assert Side.BUY.value == "BUY"
    assert get_shanghai_tz().key == "Asia/Shanghai"
    assert callable(validate_bar_schema)


def test_public_api_exports_p0_execution_types() -> None:
    assert BacktestResult.__name__ == "BacktestResult"
    assert Fill.__name__ == "Fill"
    assert NextBarMatchingModel.__name__ == "NextBarMatchingModel"
    assert Order.__name__ == "Order"
    assert OrderStatus.FILLED.value == "FILLED"
