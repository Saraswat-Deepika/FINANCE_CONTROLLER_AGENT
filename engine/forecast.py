import datetime
from typing import List, Dict, Any

def parse_date(date_str: str) -> datetime.date:
    """Safely parse various date formats into a datetime.date object."""
    if not date_str or date_str == "nan":
        return datetime.date.today()
        
    date_str = str(date_str).strip()
    formats = [
        "%Y-%m-%d", "%d-%m-%Y", "%Y/%m/%d", "%d/%m/%Y", 
        "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%S.%fZ"
    ]
    for fmt in formats:
        try:
            return datetime.datetime.strptime(date_str, fmt).date()
        except ValueError:
            continue
    return datetime.date.today()

def generate_forecast(groups: List[Dict[str, Any]], config: Dict[str, Any] = None) -> Dict[str, Any]:
    if config is None:
        config = {}
        
    min_cash_threshold = float(config.get("minimum_safe_cash", 50000.0))
    
    current_cash_position = 0.0
    pending_inflows = 0.0
    pending_outflows = 0.0
    
    # Track records for drivers
    top_inflows = []
    top_outflows = []
    
    # Store daily flows
    # format: { date_obj: {"in": 0.0, "out": 0.0, "records": []} }
    daily_flows = {}
    
    # Data quality metrics
    missing_dates = 0
    unresolved_exceptions = 0
    ambiguous_records = 0
    
    max_bank_date = None
    
    for group in groups:
        status = group.get("status", "UNKNOWN")
        
        # Exception tracking for confidence
        if status in ["NEEDS_REVIEW", "FUZZY_MATCHED", "UNMATCHED", "DUPLICATE_SUSPECTED"]:
            if not group.get("investigation_state", {}).get("resolution") in ["RESOLVED", "VALID_DIFFERENCE"]:
                unresolved_exceptions += 1
                
        # 1. Check Bank (Source of Truth for Current Cash)
        if group.get("bank"):
            bank = group["bank"]
            amt = float(bank.get("amount", 0))
            txn_type = bank.get("type", "CREDIT").upper()
            
            if txn_type == "CREDIT":
                current_cash_position += amt
            elif txn_type == "DEBIT":
                current_cash_position -= amt
                
            dt = parse_date(bank.get("date"))
            if max_bank_date is None or dt > max_bank_date:
                max_bank_date = dt
                
        # 2. Check Settlement (Pending Inflow if not in Bank)
        elif group.get("settlement"):
            settle = group["settlement"]
            amt = float(settle.get("amount", 0))
            pending_inflows += amt
            
            raw_date = settle.get("settlement_date")
            if not raw_date or raw_date == "nan":
                missing_dates += 1
                
            dt = parse_date(raw_date)
            if dt not in daily_flows:
                daily_flows[dt] = {"in": 0.0, "out": 0.0, "records": []}
            daily_flows[dt]["in"] += amt
            
            record = {
                "id": settle.get("id"),
                "description": f"Settlement {settle.get('settlement_id', '')} - {settle.get('merchant', '')}",
                "amount": amt,
                "type": "INFLOW",
                "date": dt.strftime("%Y-%m-%d"),
                "status": status
            }
            daily_flows[dt]["records"].append(record)
            top_inflows.append(record)
            
        # 3. Check Ledger (Pending In/Out if not in Bank or Settlement)
        elif group.get("ledger"):
            ledger = group["ledger"]
            amt = float(ledger.get("amount", 0))
            raw_date = ledger.get("transaction_date")
            if not raw_date or raw_date == "nan":
                missing_dates += 1
                
            dt = parse_date(raw_date)
            
            # Determine direction from account or sign
            account = ledger.get("account", "").upper()
            is_outflow = "PAYABLE" in account or amt < 0
            
            # Use absolute amount for calculations
            abs_amt = abs(amt)
            
            if dt not in daily_flows:
                daily_flows[dt] = {"in": 0.0, "out": 0.0, "records": []}
                
            record = {
                "id": ledger.get("id"),
                "description": f"Ledger {ledger.get('invoice_id', '')} - {ledger.get('customer', '')}",
                "amount": abs_amt,
                "date": dt.strftime("%Y-%m-%d"),
                "status": status
            }
                
            if is_outflow:
                pending_outflows += abs_amt
                daily_flows[dt]["out"] += abs_amt
                record["type"] = "OUTFLOW"
                top_outflows.append(record)
            else:
                pending_inflows += abs_amt
                daily_flows[dt]["in"] += abs_amt
                record["type"] = "INFLOW"
                top_inflows.append(record)
        else:
            ambiguous_records += 1

    # Define the "Current Date" as the max bank date, or today if no bank records
    current_date = max_bank_date if max_bank_date else datetime.date.today()
    
    # Generate 7-Day Forecast
    forecast_days = []
    running_balance = current_cash_position
    
    risk_alerts = []
    
    for i in range(7):
        target_date = current_date + datetime.timedelta(days=i)
        
        # Include past overdue pending items in Day 0
        day_inflow = 0.0
        day_outflow = 0.0
        day_records = []
        
        if i == 0:
            # Aggregate all overdue pending items into Day 0
            for dt, flows in daily_flows.items():
                if dt <= target_date:
                    day_inflow += flows["in"]
                    day_outflow += flows["out"]
                    day_records.extend(flows["records"])
        else:
            # Only exact matches for future days
            if target_date in daily_flows:
                flows = daily_flows[target_date]
                day_inflow += flows["in"]
                day_outflow += flows["out"]
                day_records.extend(flows["records"])
                
        net_change = day_inflow - day_outflow
        closing_balance = running_balance + net_change
        
        # Check for risk
        if closing_balance < min_cash_threshold:
            risk_alerts.append({
                "date": target_date.strftime("%Y-%m-%d"),
                "forecast_cash": closing_balance,
                "threshold": min_cash_threshold,
                "shortfall": min_cash_threshold - closing_balance
            })
            
        forecast_days.append({
            "day_index": i,
            "date": target_date.strftime("%Y-%m-%d"),
            "opening_balance": running_balance,
            "expected_inflow": day_inflow,
            "expected_outflow": day_outflow,
            "net_change": net_change,
            "closing_balance": closing_balance,
            "records_count": len(day_records)
        })
        
        running_balance = closing_balance
        
    # Calculate Confidence
    confidence = "HIGH"
    issues = []
    
    if missing_dates > 0:
        issues.append(f"{missing_dates} records missing dates")
    if unresolved_exceptions > 0:
        issues.append(f"{unresolved_exceptions} unresolved exceptions affecting forecast")
    if ambiguous_records > 0:
        issues.append(f"{ambiguous_records} ambiguous records skipped")
        
    if len(issues) >= 2 or unresolved_exceptions > 5:
        confidence = "LOW"
    elif len(issues) == 1:
        confidence = "MEDIUM"
        
    # Sort top drivers
    top_inflows = sorted(top_inflows, key=lambda x: x["amount"], reverse=True)[:5]
    top_outflows = sorted(top_outflows, key=lambda x: x["amount"], reverse=True)[:5]
    
    # Forecast Explanation
    explanation = f"Forecast starts at ₹{current_cash_position:,.2f} on {current_date.strftime('%Y-%m-%d')}. "
    explanation += f"Expected inflows: ₹{pending_inflows:,.2f}. Expected outflows: ₹{pending_outflows:,.2f}. "
    if risk_alerts:
        explanation += f"⚠️ WARNING: Cash falls below safe threshold of ₹{min_cash_threshold:,.2f} on {risk_alerts[0]['date']}. "
    else:
        explanation += "Cash position remains healthy above the minimum threshold. "
        
    if unresolved_exceptions > 0:
        explanation += f"Note: {unresolved_exceptions} unresolved exceptions reduce forecast confidence to {confidence}."
        
    return {
        "generated_at": datetime.datetime.now().isoformat(),
        "as_of_date": current_date.strftime("%Y-%m-%d"),
        "methodology": "Deterministic based on hierarchy: Bank (Actual) -> Settlement (Pending Inflow) -> Ledger (Pending I/O). Prevents double-counting via reconciliation groups.",
        "current_cash_position": current_cash_position,
        "pending_inflows": pending_inflows,
        "pending_outflows": pending_outflows,
        "net_pending_change": pending_inflows - pending_outflows,
        "confidence": confidence,
        "confidence_issues": issues,
        "minimum_safe_cash": min_cash_threshold,
        "risk_alerts": risk_alerts,
        "forecast_days": forecast_days,
        "top_drivers": {
            "inflows": top_inflows,
            "outflows": top_outflows
        },
        "explanation_summary": explanation
    }
