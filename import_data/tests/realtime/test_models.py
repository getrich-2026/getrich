from datetime import date, datetime

from import_data.realtime.models import BarEvent


def test_defaults():
    e = BarEvent(symbol="000001.SZ", type="stock", dt=date.today(), bar_time=datetime.now())
    assert e.provider == "insight"
    assert e.open == 0.0
    assert e.volume == 0.0


def test_all_fields():
    now = datetime.now()
    e = BarEvent(
        symbol="RB2510.SHF",
        type="futures",
        dt=date.today(),
        bar_time=now,
        open=3500.0,
        high=3520.0,
        low=3490.0,
        close=3510.0,
        volume=1000.0,
        amount=3510000.0,
        open_interest=50000.0,
        settle=3510.0,
        pre_settle=3505.0,
    )
    assert e.symbol == "RB2510.SHF"
    assert e.settle == 3510.0
    assert e.provider == "insight"
