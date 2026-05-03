from tools.price_data import get_stock_price

def test_valid_ticker():
    result = get_stock_price("AAPL")
    assert "error" not in result
    assert result["ticker"] == "AAPL"
    assert isinstance(result["price"], (int, float))

def test_invalid_ticker():
    result = get_stock_price("INVALID123")
    assert "error" in result