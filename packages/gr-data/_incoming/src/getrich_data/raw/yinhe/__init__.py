"""银河 raw 层：AmazingData SDK → /opt/raw_parquet/yinhe/。"""

from getrich_data.raw.yinhe.client import AmazingDataClient, YinheClient
from getrich_data.raw.yinhe.fetchers import REGISTRY

__all__ = ["AmazingDataClient", "YinheClient", "REGISTRY"]
