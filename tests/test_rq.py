import rqdatac as rq

from getrich.apps.data.etl.ricequant import init_rq

if __name__ == "__main__":
    init_rq()
    df = rq.all_instruments(type="CS", date=None, market="cn")
    print(df)
