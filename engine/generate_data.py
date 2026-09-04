import pandas as pd
import random
import uuid
import json
from datetime import datetime, timedelta

# Configuration
TOTAL_TXNS = 75
FILE_BANK = "bank_statement.csv"
FILE_SETTLEMENT = "razorpay_settlements.csv"
FILE_LEDGER = "internal_ledger.csv"
FILE_TRUTH = "ground_truth.json"

bank_data = []
settlement_data = []
ledger_data = []
ground_truth_data = []

start_date = datetime(2023, 10, 1)

def random_date(start, days=30):
    return start + timedelta(days=random.randint(0, days))

# Random names to simulate variation
names = ["Tech Corp", "Global Solutions", "Acme Inc", "Alpha Beta", "Omega LLC"]

for i in range(TOTAL_TXNS):
    # Base shared attributes
    base_amount = round(random.uniform(500.0, 5000.0), 2)
    base_dt = random_date(start_date)
    utr = f"UTR{random.randint(10000000, 99999999)}"
    inv_id = f"INV-{random.randint(10000, 99999)}"
    settle_id = f"SET-{random.randint(10000, 99999)}"
    
    chosen_name = random.choice(names)
    
    # Simulate realistic naming variations
    bank_narration = f"NEFT-{chosen_name[:4].upper()}-{utr}"
    settlement_merchant = chosen_name.lower().replace(" ", "_")
    ledger_customer = chosen_name

    # Core parameters
    b_amt, s_amt, l_amt = base_amount, base_amount, base_amount
    b_dt, s_dt, l_dt = base_dt, base_dt, base_dt
    b_utr, s_utr, l_utr = utr, utr, utr
    
    add_bank, add_settle, add_ledger = True, True, True
    duplicate_bank = False
    
    group_id = f"grp_{i+1:03d}"
    
    expected_status = "FULLY_MATCHED"
    expected_method = "EXACT_UTR"
    expected_exception_type = "NONE"

    # Default is clean match (0 to 39)
    if 40 <= i <= 44:
        # Date Shift (Settlement Delay)
        s_dt = b_dt + timedelta(days=random.randint(1, 3))
        l_dt = s_dt
        expected_status = "FUZZY_MATCHED"
        expected_method = "DATE_TOLERANCE"
        expected_exception_type = "DATE_MISMATCH"
    elif 45 <= i <= 49:
        # Amount Shift (Gateway Fee)
        s_amt = round(base_amount * 0.98, 2) # 2% fee
        expected_status = "FUZZY_MATCHED"
        expected_method = "AMOUNT_TOLERANCE"
        expected_exception_type = "GATEWAY_FEE"
    elif 50 <= i <= 52:
        # Fuzzy Match (UTR missing, rely on exact amount + date)
        s_utr = ""
        l_utr = ""
        expected_status = "FULLY_MATCHED"
        expected_method = "EXACT_AMOUNT_DATE"
    elif 53 <= i <= 55:
        # Partial Match (Missing Ledger)
        add_ledger = False
        expected_status = "PARTIAL_MATCH"
        expected_method = "EXACT_UTR"
        expected_exception_type = "MISSING_LEDGER"
    elif 56 <= i <= 58:
        # Unmatched (Only Bank)
        add_settle = False
        add_ledger = False
        expected_status = "UNMATCHED"
        expected_method = "NONE"
        expected_exception_type = "MISSING_SOURCE"
    elif 59 <= i <= 61:
        # Duplicate Bank
        duplicate_bank = True
        expected_status = "DUPLICATE_SUSPECTED"
        expected_method = "DUPLICATE_DETECTED"
        expected_exception_type = "DUPLICATE"
    elif 62 <= i <= 64:
        # Needs Review (Amounts conflict heavily - Tax difference)
        s_amt = base_amount + 500
        l_amt = base_amount - 100
        expected_status = "NEEDS_REVIEW"
        expected_method = "EXACT_UTR" 
        expected_exception_type = "AMOUNT_MISMATCH"
    elif 65 <= i <= 67:
        # Fuzzy Name match (Missing UTR, slight amount diff, name mismatch)
        b_utr, s_utr, l_utr = "", "", ""
        s_amt = base_amount - 2
        b_dt = s_dt
        settlement_merchant = "some weird name"
        expected_status = "FUZZY_MATCHED"
        expected_method = "FUZZY_MERCHANT"
        expected_exception_type = "NAME_MISMATCH"
    elif 68 <= i <= 70:
        # Refund (Negative Amount in Bank/Settle)
        b_amt, s_amt = -base_amount, -base_amount
        l_amt = -base_amount
        b_utr, s_utr, l_utr = utr, utr, utr
        expected_status = "FULLY_MATCHED"
        expected_method = "EXACT_UTR"
        expected_exception_type = "REFUND"
    elif 71 <= i <= 74:
        # Ambiguous Candidate (Same exact amount on same day for two records, but no UTR)
        # We simulate this by making the UTR blank and identical amounts.
        b_utr, s_utr, l_utr = "", "", ""
        expected_status = "NEEDS_REVIEW"
        expected_method = "AMBIGUOUS"
        expected_exception_type = "AMBIGUOUS_CANDIDATE"

    bank_id = str(uuid.uuid4())
    settle_uuid = str(uuid.uuid4())
    ledger_uuid = str(uuid.uuid4())
    
    # Add to ground truth
    ground_truth_data.append({
        "group_id": group_id,
        "expected_status": expected_status,
        "expected_method": expected_method,
        "expected_exception_type": expected_exception_type,
        "record_ids": {
            "bank": bank_id if add_bank else None,
            "settlement": settle_uuid if add_settle else None,
            "ledger": ledger_uuid if add_ledger else None
        }
    })

    # Generate records
    if add_bank:
        bank_data.append({
            "id": bank_id,
            "date": b_dt.strftime("%d-%m-%Y"),
            "amount": b_amt,
            "narration": bank_narration,
            "utr": b_utr,
            "type": "CREDIT" if b_amt > 0 else "DEBIT"
        })
        if duplicate_bank:
            bank_data.append({
                "id": str(uuid.uuid4()),
                "date": b_dt.strftime("%d-%m-%Y"),
                "amount": b_amt,
                "narration": bank_narration,
                "utr": b_utr,
                "type": "CREDIT"
            })
            
    if add_settle:
        settlement_data.append({
            "id": settle_uuid,
            "settlement_date": s_dt.strftime("%Y/%m/%d"),
            "amount": s_amt,
            "utr": s_utr,
            "settlement_id": settle_id,
            "merchant": settlement_merchant,
            "fee": round(base_amount - s_amt, 2) if s_amt < base_amount else 0
        })
        
    if add_ledger:
        ledger_data.append({
            "id": ledger_uuid,
            "transaction_date": l_dt.strftime("%Y-%m-%d"),
            "amount": l_amt,
            "utr": l_utr,
            "invoice_id": inv_id,
            "customer": ledger_customer,
            "account": "ACC-RECEIVABLE"
        })

# Shuffle to simulate reality
random.shuffle(bank_data)
random.shuffle(settlement_data)
random.shuffle(ledger_data)

pd.DataFrame(bank_data).to_csv(FILE_BANK, index=False)
pd.DataFrame(settlement_data).to_csv(FILE_SETTLEMENT, index=False)
pd.DataFrame(ledger_data).to_csv(FILE_LEDGER, index=False)

with open(FILE_TRUTH, 'w') as f:
    json.dump(ground_truth_data, f, indent=2)

print(f"Generated {len(bank_data)} bank records, {len(settlement_data)} settlement records, {len(ledger_data)} ledger records.")
print("Saved ground truth to ground_truth.json")
