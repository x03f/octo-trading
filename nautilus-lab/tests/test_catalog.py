"""Тест ParquetDataCatalog: материализация + версионирование + чтение через Nautilus."""
import sys
sys.path.insert(0,"/opt/octobot/strategy-lab/nautilus-lab"); sys.path.insert(0,"/opt/octobot/strategy-lab")
from ntlab.data.catalog import build_catalog, data_version, CATALOG_ROOT
from nautilus_trader.persistence.catalog import ParquetDataCatalog

def test_data_version_stable():
    v1=data_version(); v2=data_version()
    assert v1==v2 and len(v1)>=6      # версия детерминирована

def test_catalog_materialize_and_read():
    r=build_catalog(coins=("BTC",), tf="1d")
    assert r["total_bars"]>0
    cat=ParquetDataCatalog(r["catalog_path"])
    bars=cat.bars()
    assert len(bars)>0                # читается штатным Nautilus catalog

if __name__=="__main__":
    n=0
    for name,fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn): fn(); print(f"  ✓ {name}"); n+=1
    print(f"CATALOG: {n}/{n}")
