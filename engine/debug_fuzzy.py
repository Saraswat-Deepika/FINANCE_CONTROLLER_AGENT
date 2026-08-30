import pandas as pd
from datetime import datetime
from rapidfuzz import fuzz
from main import load_data_internally

print("=== STARTING FUZZY MATCH DEBUG ===")
df_bank, df_settle, df_ledger = load_data_internally()

# Get one unmatched bank record to debug
for bank_idx, bank_row in df_bank.iterrows():
    bank_utr = bank_row["utr_number"]
    bank_amt = float(bank_row["amount"]) if bank_row["amount"] else 0.0
    bank_date = bank_row["date"]
    
    # Check exact match first
    settle_match = df_settle[(df_settle["utr_number"] == bank_utr)]
    ledger_match = df_ledger[(df_ledger["settlement_ref"] == bank_utr)]
    
    if not settle_match.empty and not ledger_match.empty:
        continue # It's fully matched, skip
        
    print(f"\n[DEBUG] Analyzing Unmatched Bank Record:")
    print(f"UTR: {bank_utr} | Amt: {bank_amt} | Date: {bank_date} | Narration: {bank_row.get('narration', '')}")
    
    for s_idx, s_row in df_settle.iterrows():
        s_amt = float(s_row["amount"]) if s_row["amount"] else 0.0
        amt_diff = abs(bank_amt - s_amt)
        
        if amt_diff <= 100:
            try:
                b_date_obj = datetime.strptime(str(bank_date), "%Y-%m-%d")
                s_date_obj = datetime.strptime(str(s_row["settlement_date"]), "%Y-%m-%d")
                date_diff = abs((b_date_obj - s_date_obj).days)
            except Exception as e:
                date_diff = 999
                
            if date_diff <= 3:
                print(f"  [Settle Match Found] Settle ID: {s_row.get('settlement_id', '')} | Amt Diff: {amt_diff} | Date Diff: {date_diff} days")
                for l_idx, l_row in df_ledger.iterrows():
                    l_amt = float(l_row["amount"]) if l_row["amount"] else 0.0
                    l_amt_diff = abs(bank_amt - l_amt)
                    
                    if l_amt_diff <= 100:
                        b_narr = str(bank_row.get("narration", "")).lower()
                        l_name = str(l_row.get("customer_name", "")).lower()
                        name_sim = fuzz.token_set_ratio(b_narr, l_name)
                        print(f"    [Ledger Candidate] Ledger ID: {l_row.get('invoice_id', '')}")
                        print(f"      Bank Narration: '{b_narr}' vs Ledger Name: '{l_name}'")
                        print(f"      Token Set Ratio Score: {name_sim}%")
                        if name_sim >= 75:
                            print("      -> MATCH SUCCESSFUL (Score >= 75)")
                        else:
                            print("      -> FAILED (Score < 75)")
    break # Just debug one record for now
print("=== END DEBUG ===")
