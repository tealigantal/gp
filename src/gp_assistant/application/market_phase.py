from datetime import datetime, time
from ..contracts.catalog import MarketPhase

def market_phase(now: datetime) -> MarketPhase:
    local_time = now.timetz().replace(tzinfo=None)
    if local_time < time(9, 30):
        return MarketPhase.PREOPEN
    if local_time < time(11, 30):
        return MarketPhase.MORNING
    if local_time < time(13, 0):
        return MarketPhase.LUNCH
    if local_time < time(14, 57):
        return MarketPhase.AFTERNOON
    if local_time < time(15, 0):
        return MarketPhase.CLOSING_AUCTION
    return MarketPhase.POSTCLOSE


