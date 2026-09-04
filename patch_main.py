import re

with open("engine/main.py", "r") as f:
    content = f.read()

# Add import at the top
if "from evidence import build_evidence" not in content:
    content = content.replace("from datetime import datetime\n", "from datetime import datetime\nfrom evidence import build_evidence\n")

# Modify Exact Match
old_exact = """                fully_matched.append({
                    "bank": bank_row.to_dict(),
                    "settlement": df_settle.loc[s_idx].to_dict(),
                    "ledger": df_ledger.loc[l_idx].to_dict()
                })"""
new_exact = """                bank_dict = bank_row.to_dict()
                settle_dict = df_settle.loc[s_idx].to_dict()
                ledger_dict = df_ledger.loc[l_idx].to_dict()
                
                ev_data = build_evidence(bank_dict, settle_dict, ledger_dict, "FULLY_MATCHED")
                ev_data["bank"] = bank_dict
                ev_data["settlement"] = settle_dict
                ev_data["ledger"] = ledger_dict
                
                fully_matched.append(ev_data)"""
content = content.replace(old_exact, new_exact)

# Modify Fuzzy Match Assignment
old_match_data = """                match_data = {
                    "confidence_score": score,
                    "bank": bank_row.to_dict(),
                    "settlement": df_settle.loc[s_idx].to_dict(),
                    "ledger": df_ledger.loc[l_idx].to_dict()
                }"""
new_match_data = """                bank_dict = bank_row.to_dict()
                settle_dict = df_settle.loc[s_idx].to_dict()
                ledger_dict = df_ledger.loc[l_idx].to_dict()
                
                factors = [
                    {"factor": "Name similarity", "score": round(name_sim / 100, 2), "weight": 0.40},
                    {"factor": "Amount similarity", "score": round(amt_sim / 100, 2), "weight": 0.40},
                    {"factor": "Date similarity", "score": round(date_sim / 100, 2), "weight": 0.20}
                ]
                
                status = "FUZZY_MATCHED" if score >= 70 else "NEEDS_REVIEW"
                match_data = build_evidence(bank_dict, settle_dict, ledger_dict, status, score / 100, factors)
                match_data["bank"] = bank_dict
                match_data["settlement"] = settle_dict
                match_data["ledger"] = ledger_dict"""
content = content.replace(old_match_data, new_match_data)

# Modify Unmatched (Bank)
old_unmatched_bank = """            unmatched.append({
                "source": "bank_statement",
                "record": bank_row.to_dict()
            })"""
new_unmatched_bank = """            bank_dict = bank_row.to_dict()
            ev_data = build_evidence(bank_dict, None, None, "UNMATCHED")
            ev_data["source"] = "bank_statement"
            ev_data["record"] = bank_dict
            unmatched.append(ev_data)"""
content = content.replace(old_unmatched_bank, new_unmatched_bank)

# Modify Unmatched (Settlement)
old_unmatched_settle = """                unmatched.append({
                    "source": "settlement",
                    "record": s_row.to_dict()
                })"""
new_unmatched_settle = """                settle_dict = s_row.to_dict()
                ev_data = build_evidence(None, settle_dict, None, "UNMATCHED")
                ev_data["source"] = "settlement"
                ev_data["record"] = settle_dict
                unmatched.append(ev_data)"""
content = content.replace(old_unmatched_settle, new_unmatched_settle)

# Modify Unmatched (Ledger)
old_unmatched_ledger = """                unmatched.append({
                    "source": "ledger",
                    "record": l_row.to_dict()
                })"""
new_unmatched_ledger = """                ledger_dict = l_row.to_dict()
                ev_data = build_evidence(None, None, ledger_dict, "UNMATCHED")
                ev_data["source"] = "ledger"
                ev_data["record"] = ledger_dict
                unmatched.append(ev_data)"""
content = content.replace(old_unmatched_ledger, new_unmatched_ledger)

with open("engine/main.py", "w") as f:
    f.write(content)
print("Patched main.py")
