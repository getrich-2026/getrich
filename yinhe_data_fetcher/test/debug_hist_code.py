from __future__ import annotations
import os
import sys
import traceback
import pandas as pd

repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if repo_root not in sys.path:
    sys.path.append(repo_root)

from src.config import Config
from src.client import AmazingDataClient

def test_debug():
    cfg = Config.load(os.path.join(repo_root, "config.yaml"))
    client = AmazingDataClient(cfg.amazing_data)
    client.login()
    bd = client.base_data
    sdk_cache = os.path.join(cfg.storage.data_dir, "_sdk_cache", "hist_code_list")
    
    # Query 2025 month-by-month
    for m in range(1, 13):
        start_dt = 20250000 + m * 100 + 1
        end_dt = 20250000 + m * 100 + 31 # rough end date
        if m == 2:
            end_dt = 20250228
        elif m in [4, 6, 9, 11]:
            end_dt = 20250000 + m * 100 + 30
            
        print(f"Querying month 2025-{m:02d} [{start_dt}, {end_dt}]...")
        res = bd.get_hist_code_list(
            security_type="EXTRA_STOCK_A_SH_SZ",
            start_date=start_dt,
            end_date=end_dt,
            local_path=sdk_cache + "/"
        )
        print(f"Finished month 2025-{m:02d}! type: {type(res)}")
        if res is not None:
            print(f"Rows: {len(res)}")

if __name__ == "__main__":
    try:
        test_debug()
    except Exception as e:
        traceback.print_exc()
