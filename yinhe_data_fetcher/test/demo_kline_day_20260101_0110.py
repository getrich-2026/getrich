from __future__ import annotations

import os
import sys
import traceback


def main() -> int:
    """
    Minimal AmazingData demo:
    - login
    - get_calendar
    - MarketData(calendar).query_kline for day K

    Usage:
      conda run -n get_rich_main python -u test/demo_kline_day_20260101_0110.py

    Optional env vars:
      GOLD_MINER_USERNAME / GOLD_MINER_PASSWORD / GOLD_MINER_HOST / GOLD_MINER_PORT
      GOLD_MINER_CODE (default: 600000.SH)
      GOLD_MINER_BEGIN (default: 20260101)
      GOLD_MINER_END   (default: 20260110)
    """

    username = os.environ.get("GOLD_MINER_USERNAME", "228200018953")
    password = os.environ.get("GOLD_MINER_PASSWORD", "228200018953@2026")
    host = os.environ.get("GOLD_MINER_HOST", "101.230.159.234")
    port = int(os.environ.get("GOLD_MINER_PORT", "8600"))

    code = os.environ.get("GOLD_MINER_CODE", "600000.SH")
    begin_date = int(os.environ.get("GOLD_MINER_BEGIN", "20260101"))
    end_date = int(os.environ.get("GOLD_MINER_END", "20260110"))

    print("python:", sys.version.replace("\n", " "), flush=True)
    print("login:", host, port, "user=", username, flush=True)
    print("code:", code, "range:", begin_date, "-", end_date, flush=True)

    try:
        import AmazingData as ad  # type: ignore

        ad.login(username=username, password=password, host=host, port=port)
        print("login: ok", flush=True)

        base_data = ad.BaseData()
        calendar = base_data.get_calendar(market="SH")
        if calendar is None:
            raise RuntimeError("get_calendar returned None")
        calendar = list(calendar)
        print("calendar: ok len=", len(calendar), "last=", calendar[-1] if calendar else None, flush=True)

        md = ad.MarketData(calendar)
        period = ad.constant.Period.day.value
        print("query_kline: start period=", period, flush=True)

        # query_kline accepts a list of codes; return is usually dict-like keyed by code.
        res = md.query_kline([code], begin_date=begin_date, end_date=end_date, period=period)
        print("query_kline: ok type=", type(res), flush=True)

        try:
            one = res.get(code) if hasattr(res, "get") else None
            if one is None and isinstance(res, dict) and len(res) == 1:
                one = next(iter(res.values()))
            if one is not None and hasattr(one, "head"):
                print(one.head(5), flush=True)
            else:
                print("result_preview:", str(res)[:800], flush=True)
        except Exception:  # noqa: BLE001
            print("result_preview_failed", flush=True)

        return 0
    except Exception as e:  # noqa: BLE001
        print("FAIL:", type(e).__name__, str(e), flush=True)
        traceback.print_exc()
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

