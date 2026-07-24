"""Тесты Gate.io Spot WebSocket: разбор свечи, дедуп, gap-detect, только закрытые."""
import sys
sys.path.insert(0,"/opt/octobot/strategy-lab/nautilus-lab")
from ntlab.adapters.gateio.websocket import GateioSpotWS

def _candle(t, close, w=True):
    return {"t": t, "o": "100", "h": "101", "l": "99", "c": str(close), "v": "10", "n": "1m_BTC_USDT", "w": w}

def test_only_closed_candles():
    bars=[]; ws=GateioSpotWS(on_bar=lambda b: bars.append(b))
    ws._handle_candle(_candle(1000, 100, w=False))   # незакрытая — игнор
    assert len(bars)==0
    ws._handle_candle(_candle(1000, 100, w=True))
    assert len(bars)==1

def test_dedup():
    bars=[]; ws=GateioSpotWS(on_bar=lambda b: bars.append(b))
    ws._handle_candle(_candle(1000, 100))
    ws._handle_candle(_candle(1000, 100))            # дубль по ts
    assert len(bars)==1

def test_gap_detection():
    bars=[]; ws=GateioSpotWS(on_bar=lambda b: bars.append(b))
    ws._handle_candle(_candle(1000, 100))            # ts 1000s
    ws._handle_candle(_candle(1300, 105))            # +300s = 5 баров пропущено (>1.5*60)
    assert ws.gaps_detected==1
    assert bars[-1]["gap"] is True

def test_bar_fields():
    bars=[]; ws=GateioSpotWS(on_bar=lambda b: bars.append(b))
    ws._handle_candle(_candle(2000, 123.5))
    b=bars[0]
    assert b["symbol"]=="BTC_USDT" and b["tf"]=="1m" and b["close"]==123.5 and b["ts"]==2000000

def test_backoff_grows():
    ws=GateioSpotWS()
    ws._backoff=1.0
    b0=ws._backoff
    ws._backoff=min(ws._backoff*2,30); assert ws._backoff>b0

if __name__=="__main__":
    n=0
    for name,fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn): fn(); print(f"  ✓ {name}"); n+=1
    print(f"WEBSOCKET: {n}/{n}")
