# Import from new API location
from getrich.apps.data.api.rqapi import RQDataAPI

from .constants import INSTRUMENT_TYPES
from .instrument import export_all_instruments


# Backward compatibility - provide init_rq function
def init_rq() -> RQDataAPI:
    """Initialize RiceQuant connection (backward compatibility wrapper)"""
    api = RQDataAPI()
    api.login()
    return api


__all__ = ["init_rq", "INSTRUMENT_TYPES", "export_all_instruments", "RQDataAPI"]
