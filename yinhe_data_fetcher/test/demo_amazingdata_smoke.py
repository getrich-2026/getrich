from __future__ import annotations

import importlib.metadata
import os
import socket
import sys
import traceback

print("module_loaded: demo_amazingdata_smoke", flush=True)


def _version(name: str) -> str:
    try:
        return importlib.metadata.version(name)
    except Exception:  # noqa: BLE001
        return "unknown"


def _tcp_probe(host: str, port: int, timeout_sec: float = 5.0) -> tuple[bool, str]:
    try:
        with socket.create_connection((host, port), timeout=timeout_sec):
            return True, "tcp_connect_ok"
    except Exception as e:  # noqa: BLE001
        return False, f"tcp_connect_fail: {type(e).__name__}: {e}"


def main() -> int:
    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    print("demo_start: repo_root=", repo_root, flush=True)
    if repo_root not in sys.path:
        # Avoid shadowing installed SDK modules; append instead of prepend.
        sys.path.append(repo_root)
    print("demo_start: sys.path[0:3]=", sys.path[:3], flush=True)

    from src.config import Config
    from src.client import AmazingDataClient

    cfg = Config.load(os.environ.get("GOLD_MINER_CONFIG", os.path.join(repo_root, "config.yaml")))

    print("=== env ===", flush=True)
    print("python:", sys.version.replace("\n", " "), flush=True)
    print("tgw:", _version("tgw"), flush=True)
    print("AmazingData:", _version("AmazingData"), flush=True)
    print("host:", cfg.amazing_data.host)
    print("port:", cfg.amazing_data.port)
    ok, msg = _tcp_probe(cfg.amazing_data.host, cfg.amazing_data.port)
    print("tcp_probe:", ok, msg, flush=True)
    print("", flush=True)

    print("=== login ===", flush=True)
    client = AmazingDataClient(cfg.amazing_data)
    try:
        client.login()
        print("login: ok", flush=True)
    except ModuleNotFoundError as e:
        # SDK wheel is provided out-of-band by the broker; allow a "tcp-only" smoke run.
        allow_no_sdk = os.environ.get("GOLD_MINER_ALLOW_NO_SDK", "").strip().lower() in (
            "1",
            "true",
            "yes",
            "y",
            "on",
        )
        if allow_no_sdk and ok:
            print("login: SKIP (AmazingData not installed)", flush=True)
            print("hint: install AmazingData wheel then rerun without GOLD_MINER_ALLOW_NO_SDK", flush=True)
            return 0
        print("login: FAIL", type(e).__name__, str(e), flush=True)
        print("hint: pip install AmazingData-<version>-py3-none-any.whl", flush=True)
        traceback.print_exc()
        return 2
    except Exception as e:  # noqa: BLE001
        print("login: FAIL", type(e).__name__, str(e), flush=True)
        traceback.print_exc()
        return 2
    print("", flush=True)

    print("=== BaseData smoke ===", flush=True)
    bd = client.base_data

    # 1) calendar
    try:
        cal = bd.get_calendar(market="SH")
        cal_list = list(cal) if cal is not None else None
        print("get_calendar: ok", "len=", (len(cal_list) if cal_list else None), "head=", (cal_list[:5] if cal_list else None))
    except Exception as e:  # noqa: BLE001
        print("get_calendar: FAIL", type(e).__name__, str(e))
        traceback.print_exc()

    # 2) code list (沪深 A 股)
    try:
        codes = bd.get_code_list(security_type="EXTRA_STOCK_A_SH_SZ")
        codes_list = list(codes) if codes is not None else None
        print("get_code_list: ok", "len=", (len(codes_list) if codes_list else None), "head=", (codes_list[:5] if codes_list else None))
    except Exception as e:  # noqa: BLE001
        print("get_code_list: FAIL", type(e).__name__, str(e))
        traceback.print_exc()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

