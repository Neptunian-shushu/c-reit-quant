from creit_quant.schema import ReitMaster


def test_master():
    x = ReitMaster(symbol="508097", name="sample", exchange="SSE", asset_type="industrial_park")
    assert x.symbol == "508097"
