import datetime
from forecast import parse_date, generate_forecast

def test_parse_date():
    assert parse_date("2023-10-01") == datetime.date(2023, 10, 1)
    assert parse_date("01-10-2023") == datetime.date(2023, 10, 1)
    assert parse_date("nan") == datetime.date.today()

def test_forecast_basic():
    groups = [
        {
            "status": "FULLY_MATCHED",
            "bank": {"amount": 1000, "type": "CREDIT", "date": "2023-10-01"},
            "settlement": {"amount": 1000, "settlement_date": "2023-10-01"}
        },
        {
            "status": "FULLY_MATCHED",
            "bank": {"amount": 500, "type": "DEBIT", "date": "2023-10-01"}
        },
        {
            "status": "UNMATCHED",
            "settlement": {"amount": 200, "settlement_date": "2023-10-02", "id": "s1", "merchant": "Merch1"}
        },
        {
            "status": "UNMATCHED",
            "ledger": {"amount": -100, "transaction_date": "2023-10-03", "id": "l1"}
        }
    ]
    
    result = generate_forecast(groups, {"minimum_safe_cash": 100})
    
    assert result["current_cash_position"] == 500.0  # 1000 credit - 500 debit
    assert result["as_of_date"] == "2023-10-01"
    
    assert result["pending_inflows"] == 200.0
    assert result["pending_outflows"] == 100.0
    assert result["net_pending_change"] == 100.0
    
    # Check that day 1 (2023-10-02) has 200 inflow
    assert result["forecast_days"][1]["expected_inflow"] == 200.0
    # Check that day 2 (2023-10-03) has 100 outflow
    assert result["forecast_days"][2]["expected_outflow"] == 100.0
    
    # Final cash position
    assert result["forecast_days"][6]["closing_balance"] == 600.0

def test_forecast_confidence():
    groups = [
        {
            "status": "NEEDS_REVIEW",
            "settlement": {"amount": 200, "settlement_date": "nan"}
        },
        {
            "status": "UNMATCHED",
            "ledger": {"amount": 100, "transaction_date": "2023-10-03"}
        }
    ]
    
    result = generate_forecast(groups, {"minimum_safe_cash": 100})
    assert result["confidence"] == "LOW"  # 1 missing date + 2 exceptions

def test_forecast_risk():
    groups = [
        {
            "status": "FULLY_MATCHED",
            "bank": {"amount": 100000, "type": "CREDIT", "date": "2023-10-01"}
        },
        {
            "status": "UNMATCHED",
            "ledger": {"amount": -60000, "transaction_date": "2023-10-03"}
        }
    ]
    
    result = generate_forecast(groups, {"minimum_safe_cash": 50000})
    assert len(result["risk_alerts"]) > 0
    assert result["risk_alerts"][0]["date"] == "2023-10-03"

if __name__ == "__main__":
    test_parse_date()
    test_forecast_basic()
    test_forecast_confidence()
    test_forecast_risk()
    print("All tests passed!")
