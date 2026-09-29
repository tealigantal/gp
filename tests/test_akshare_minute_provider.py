from datetime import datetime, timezone
import pandas as pd
import pytest
import requests
from gp_assistant.providers.akshare_provider import AkShareProvider
from gp_assistant.providers.sina_minutes import SinaMinuteProvider

@pytest.mark.parametrize("index,symbol", [(False,"600519"),(True,"000300")])
def test_single_source_preserves_true_amount_and_window(monkeypatch,index,symbol):
    calls=[]
    def fetch(self, code, **kwargs):
        calls.append((code,kwargs))
        return pd.DataFrame({"trade_time":["2026-07-07 11:25","2026-07-07 11:30","2026-07-07 11:35"],"vol":[100,150,100],"amount":[1005,1525,1000],"close":[10.1,10.3,10]}),datetime.now(timezone.utc),1
    monkeypatch.setattr(SinaMinuteProvider,"fetch",fetch)
    p=AkShareProvider(timeout_sec=3)
    frame=(p.get_index_minute_bars_5m if index else p.get_minute_bars_5m)(symbol,"2026-07-07 11:25","2026-07-07 11:30")
    assert calls==[(symbol,{"index":True} if index else {})]
    assert list(frame.amount)==[1005,1525]
    assert list(frame.vol)==[100,150]

def test_source_failure_is_not_retried_or_replaced(monkeypatch):
    calls=[]
    def get(*args,**kwargs):
        calls.append(kwargs)
        raise requests.Timeout("source timeout")
    monkeypatch.setattr(requests,"get",get)
    with pytest.raises(requests.Timeout,match="source timeout"):
        AkShareProvider().get_minute_bars_5m("600519","2026-07-07 11:25","2026-07-07 11:30")
    assert len(calls)==1
    assert calls[0]["params"]["symbol"]=="sh600519"
    assert calls[0]["timeout"]==8
