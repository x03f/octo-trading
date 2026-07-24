"""Тесты Gate.io Futures adapter: hostname-safety, order-guard, availability-структура."""
import sys
sys.path.insert(0,"/opt/octobot/strategy-lab/nautilus-lab")
from ntlab.adapters.gateio.futures import GateioFuturesPrivate, TESTNET_BASE, _assert_testnet

def test_hostname_safety_blocks_mainnet():
    try:
        GateioFuturesPrivate("k","s",base="https://api.gateio.ws")
        assert False, "mainnet должен быть заблокирован"
    except PermissionError:
        pass

def test_assert_testnet_allows_testnet():
    _assert_testnet(TESTNET_BASE)   # не должно кидать

def test_private_needs_keys():
    try:
        GateioFuturesPrivate("","",base=TESTNET_BASE)
        assert False
    except ValueError:
        pass

def test_testnet_order_disabled_by_default():
    p=GateioFuturesPrivate("k","s",base=TESTNET_BASE,live_testnet_enabled=False)
    try:
        p.place_order("BTC_USDT", 1, 65000)
        assert False, "ордер должен быть заблокирован"
    except PermissionError:
        pass
    finally:
        p.close()

def test_cid_prefix_testnet():
    p=GateioFuturesPrivate("k","s",base=TESTNET_BASE)
    assert p.CID_PREFIX == "t-tn"   # отдельный TestNet-префикс
    p.close()

if __name__=="__main__":
    n=0
    for name,fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn): fn(); print(f"  ✓ {name}"); n+=1
    print(f"FUTURES TESTNET ADAPTER: {n}/{n}")
