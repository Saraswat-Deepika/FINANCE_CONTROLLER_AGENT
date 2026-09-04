from typing import Dict, Any, List

def build_evidence(bank: Dict, settle: Dict, ledger: Dict, status: str, score: float = None, factors: List = None) -> Dict:
    evidence = {}
    matched_fields = []
    mismatched_fields = []
    missing_sources = []
    
    # Calculate amounts
    b_amt = float(bank.get("amount", 0)) if bank else None
    s_amt = float(settle.get("amount", 0)) if settle else None
    l_amt = float(ledger.get("amount", 0)) if ledger else None
    
    evidence["amount"] = {
        "bank": b_amt,
        "settlement": s_amt,
        "ledger": l_amt
    }
    
    if bank and settle:
        diff = round(abs(b_amt - s_amt), 2)
        evidence["amount"]["difference"] = diff
        if diff == 0: matched_fields.append("Amount")
        else: mismatched_fields.append("Amount")
    elif bank and ledger:
        diff = round(abs(b_amt - l_amt), 2)
        evidence["amount"]["difference"] = diff
        if diff == 0: matched_fields.append("Amount")
        else: mismatched_fields.append("Amount")
        
    # Calculate dates
    b_date = bank.get("date") if bank else None
    s_date = settle.get("date") if settle else None
    l_date = ledger.get("date") if ledger else None
    
    evidence["date"] = {
        "bank": b_date,
        "settlement": s_date,
        "ledger": l_date
    }
    
    try:
        from datetime import datetime
        if b_date and s_date:
            b_obj = datetime.strptime(b_date, "%Y-%m-%d")
            s_obj = datetime.strptime(s_date, "%Y-%m-%d")
            diff_days = abs((b_obj - s_obj).days)
            evidence["date"]["difference_days"] = diff_days
            if diff_days == 0: matched_fields.append("Date")
            else: mismatched_fields.append("Date")
    except:
        pass
        
    # Reference
    b_utr = bank.get("utr") if bank else None
    s_utr = settle.get("utr") if settle else None
    l_utr = ledger.get("utr") if ledger else None
    
    evidence["reference"] = {
        "bank": b_utr,
        "settlement": s_utr,
        "ledger": l_utr
    }
    
    if b_utr and s_utr:
        if str(b_utr) == str(s_utr): matched_fields.append("UTR")
        else: mismatched_fields.append("UTR")
        
    # Missing Sources
    if not bank: missing_sources.append("Bank Statement")
    if not settle: missing_sources.append("Settlement")
    if not ledger: missing_sources.append("Internal Ledger")
    
    # Recommendations
    recommendation = ""
    if status == "FULLY_MATCHED":
        recommendation = "No action required"
    elif status == "FUZZY_MATCHED":
        if "Amount" in mismatched_fields:
            recommendation = "Monitor settlement; possible gateway fee"
        elif "Date" in mismatched_fields:
            recommendation = "Monitor settlement; no manual correction required"
        else:
            recommendation = "Review differences"
    elif status == "PARTIAL_MATCH":
        recommendation = "Investigate missing source to complete reconciliation"
    elif status == "NEEDS_REVIEW":
        recommendation = "Human verification required"
    elif status == "UNMATCHED":
        recommendation = "Investigate missing entries"
    elif status == "DUPLICATE_SUSPECTED":
        recommendation = "Verify if transaction was processed twice"
        
    final_score = score if score is not None else (1.0 if status == "FULLY_MATCHED" else 0.0)
    
    res = {
        "status": status,
        "confidence": final_score,
        "confidence_percentage": round(final_score * 100, 1),
        "evidence": evidence,
        "matched_fields": list(set(matched_fields)),
        "mismatched_fields": list(set(mismatched_fields)),
        "missing_sources": missing_sources,
        "recommendation": recommendation
    }
    
    if factors:
        res["confidence_factors"] = factors
        
    return res
