import pandas as pd
import random
from datetime import datetime, timedelta

# Configuration
TOTAL_TXNS = 60
FILE_BANK = "bank_statement.csv"
FILE_SETTLEMENT = "razorpay_settlements.csv"
FILE_LEDGER = "internal_ledger.csv"

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
    
    chosen_name = random.choice(names)
    
    # Simulate realistic naming variations
    bank_narration = f"NEFT-{chosen_name[:4].upper()}-{utr}"
    settlement_merchant = chosen_name.lower().replace(" ", "_")
    ledger_customer = chosen_name

    # Scenario logic based on requested percentages
    b_amt, s_amt, l_amt = base_amount, base_amount, base_amount
    b_dt, s_dt, l_dt = base_dt, base_dt, base_dt
    
    add_bank, add_settle, add_ledger = True, True, True
    group_id = f"grp_{i+1:03d}"
    
    fate = "clean_match"
    true_category = "Fully Matched"
    expected_reason = "Perfect match across all sources"

    if 33 <= i <= 41:
        # 15%: date shifted 1-3 days (settlement delay)
        s_dt = b_dt + timedelta(days=random.randint(1, 3))
        l_dt = s_dt
        fate = "date_shift"
        true_category = "Fuzzy Matched"
        expected_reason = "Settlement delayed by 1-3 days"
    elif 42 <= i <= 47:
        # 10%: amount is less in settlement (gateway fee)
        s_amt = round(base_amount * 0.98, 2)
        fate = "amount_mismatch"
        true_category = "Fuzzy Matched"
        expected_reason = "Gateway fee deducted"
    elif 48 <= i <= 52:
        # 8%: missing in bank statement
        add_bank = False
        fate = "missing_in_bank"
        true_category = "Unmatched"
        expected_reason = "Missing in Bank Statement"
    elif 53 <= i <= 56:
        # 7%: missing in internal ledger
        add_ledger = False
        fate = "missing_in_ledger"
        true_category = "Unmatched"
        expected_reason = "Missing in Internal Ledger"
    elif 57 <= i <= 59:
        # 5%: missing in settlement
        add_settle = False
        fate = "missing_in_settlement"
        true_category = "Unmatched"
        expected_reason = "Missing in Settlement"
        
    # Add to ground truth
    ground_truth_data.append({
        "group_id": group_id,
        "true_category": true_category,
        "expected_reason": expected_reason,
        "fate": fate
    })

    # Add to lists with different date formats to simulate real-world messiness
    if add_bank:
        bank_data.append({
            "group_id": group_id,
            "date": b_dt.strftime("%d-%m-%Y"),
            "amount": b_amt,
            "narration": bank_narration,
            "utr_number": utr
        })
    if add_settle:
        settlement_data.append({
            "group_id": group_id,
            "settlement_id": f"setl_{random.randint(10000, 99999)}",
            "amount": s_amt,
            "utr_number": utr,
            "settlement_date": s_dt.strftime("%Y/%m/%d"),
            "merchant_name": settlement_merchant
        })
    if add_ledger:
        ledger_data.append({
            "group_id": group_id,
            "invoice_id": inv_id,
            "amount": l_amt,
            "customer_name": ledger_customer,
            "invoice_date": l_dt.strftime("%Y-%m-%d"),
            "settlement_ref": utr
        })

# Create Pandas DataFrames
df_bank = pd.DataFrame(bank_data)
df_settle = pd.DataFrame(settlement_data)
df_ledger = pd.DataFrame(ledger_data)
df_truth = pd.DataFrame(ground_truth_data)

# Save to CSV
df_bank.to_csv(FILE_BANK, index=False)
df_settle.to_csv(FILE_SETTLEMENT, index=False)
df_ledger.to_csv(FILE_LEDGER, index=False)
df_truth.to_csv("ground_truth.csv", index=False)

print("4 Synthetic CSV files generated successfully with messy data and ground truth!")
