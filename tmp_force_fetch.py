from gp_assistant.recommend.datahub import MarketDataHub
import pandas as pd, os
hub = MarketDataHub()
df, meta = hub.daily_ohlcv('600900', as_of=None, min_len=0, prefer_cache_only=False, force_network=True)
print('meta_source=', meta.get('source'), 'cache=', meta.get('cache'), 'target=', meta.get('target_trading_day'), 'rollover=', meta.get('rollover_forced'))
if df is None or len(df)==0:
    print('no_bars')
else:
    last = df.iloc[-1]
    print('last_date=', pd.to_datetime(last['date']).date().isoformat(), 'close=', float(last['close']))
