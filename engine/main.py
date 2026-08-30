import pandas as pd
import os
from fastapi import FastAPI
import uvicorn
from rapidfuzz import fuzz
from datetime import datetime

# Import AI reasoning function
try:
    from reasoning_graph import run_reconciliation_graph
except ImportError:
    run_reconciliation_graph = None

app = FastAPI(title="Finance Controller Engine", description="AI reconciliation service")

@app.get("/health")
def health_check():
    return {"status": "ok", "message": "FastAPI engine is running smoothly!"}

def load_data_internally():
    if not os.path.exists("bank_statement.csv"):
        raise Exception("Data files not found. Please run generate_data.py first.")
        
    df_bank = pd.read_csv("bank_statement.csv")
    df_settle = pd.read_csv("razorpay_settlements.csv")
    df_ledger = pd.read_csv("internal_ledger.csv")
    
    df_bank["amount"] = pd.to_numeric(df_bank["amount"], errors="coerce").fillna(0.0)
    df_settle["amount"] = pd.to_numeric(df_settle["amount"], errors="coerce").fillna(0.0)
    df_ledger["amount"] = pd.to_numeric(df_ledger["amount"], errors="coerce").fillna(0.0)
    
    df_bank["date"] = pd.to_datetime(df_bank["date"], format="%d-%m-%Y", errors="coerce").dt.strftime("%Y-%m-%d")
    df_settle["settlement_date"] = pd.to_datetime(df_settle["settlement_date"], format="%Y/%m/%d", errors="coerce").dt.strftime("%Y-%m-%d")
    df_ledger["invoice_date"] = pd.to_datetime(df_ledger["invoice_date"], format="%Y-%m-%d", errors="coerce").dt.strftime("%Y-%m-%d")
    
    df_bank = df_bank.where(pd.notnull(df_bank), None)
    df_settle = df_settle.where(pd.notnull(df_settle), None)
    df_ledger = df_ledger.where(pd.notnull(df_ledger), None)
    
    # Ignore group_id for reconciliation engine processing
    # (Kept in dataframe so it's present in JSON output for /evaluate)
    # df_bank = df_bank.drop(columns=['group_id'], errors='ignore')
    # df_settle = df_settle.drop(columns=['group_id'], errors='ignore')
    # df_ledger = df_ledger.drop(columns=['group_id'], errors='ignore')
    
    return df_bank, df_settle, df_ledger

@app.post("/load-data")
def load_data():
    try:
        df_bank, df_settle, df_ledger = load_data_internally()
        return {
            "status": "success",
            "data": {
                "bank_statements": df_bank.to_dict(orient="records"),
                "settlements": df_settle.to_dict(orient="records"),
                "ledger": df_ledger.to_dict(orient="records")
            }
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}

@app.post("/reconcile")
def reconcile():
    try:
        df_bank, df_settle, df_ledger = load_data_internally()
        
        fully_matched = []
        fuzzy_matched = []
        needs_review = []
        unmatched = []
        
        matched_settle_indices = set()
        matched_ledger_indices = set()
        
        for bank_idx, bank_row in df_bank.iterrows():
            bank_utr = bank_row["utr_number"]
            bank_amt = float(bank_row["amount"]) if bank_row["amount"] else 0.0
            bank_date = bank_row["date"]
            
            # Step 1 — Exact Match (Require UTR, Amount, and Date to match perfectly)
            settle_match = df_settle[(df_settle["utr_number"] == bank_utr) & 
                                     (df_settle["amount"].astype(float) == bank_amt) & 
                                     (df_settle["settlement_date"] == bank_date) & 
                                     (~df_settle.index.isin(matched_settle_indices))]
                                     
            ledger_match = df_ledger[(df_ledger["settlement_ref"] == bank_utr) & 
                                     (df_ledger["amount"].astype(float) == bank_amt) & 
                                     (df_ledger["invoice_date"] == bank_date) & 
                                     (~df_ledger.index.isin(matched_ledger_indices))]
            
            if not settle_match.empty and not ledger_match.empty:
                s_idx = settle_match.index[0]
                l_idx = ledger_match.index[0]
                
                matched_settle_indices.add(s_idx)
                matched_ledger_indices.add(l_idx)
                
                fully_matched.append({
                    "bank": bank_row.to_dict(),
                    "settlement": df_settle.loc[s_idx].to_dict(),
                    "ledger": df_ledger.loc[l_idx].to_dict()
                })
                continue
                
            # Step 2 — Fuzzy Match
            best_fuzzy_match = None
            best_score = 0
            
            for s_idx, s_row in df_settle.iterrows():
                if s_idx in matched_settle_indices:
                    continue
                
                s_amt = float(s_row["amount"]) if s_row["amount"] else 0.0
                
                if abs(bank_amt - s_amt) <= 100:
                    try:
                        b_date_obj = datetime.strptime(bank_date, "%Y-%m-%d")
                        s_date_obj = datetime.strptime(s_row["settlement_date"], "%Y-%m-%d")
                        date_diff = abs((b_date_obj - s_date_obj).days)
                    except:
                        date_diff = 999
                        
                    if date_diff <= 3:
                        for l_idx, l_row in df_ledger.iterrows():
                            if l_idx in matched_ledger_indices:
                                continue
                                
                            l_amt = float(l_row["amount"]) if l_row["amount"] else 0.0
                            
                            if abs(bank_amt - l_amt) <= 100:
                                b_narr = str(bank_row["narration"]).lower().replace("-", " ").replace("_", " ")
                                l_name = str(l_row["customer_name"]).lower().replace("-", " ").replace("_", " ")
                                
                                # Weighted Scoring
                                name_sim = fuzz.token_set_ratio(b_narr, l_name)
                                
                                max_amt = max(bank_amt, 1)
                                amt_diff_percent = (abs(bank_amt - l_amt) / max_amt) * 100
                                amt_sim = max(0, 100 - amt_diff_percent)
                                
                                date_sim = max(0, 100 - (date_diff * 33))
                                
                                final_score = (name_sim * 0.4) + (amt_sim * 0.4) + (date_sim * 0.2)
                                
                                # DEBUG PRINTS
                                print(f"[Fuzzy Candidate] Bank: {b_narr} | Ledger: {l_name} | Name: {name_sim}% | Amt: {amt_sim:.1f}% | Date: {date_sim}% | Final: {final_score:.1f}%")
                                
                                if final_score >= 40 and final_score > best_score:
                                    best_score = final_score
                                    best_fuzzy_match = (s_idx, l_idx, final_score)
                                    print(f"  -> SUCCESS! Found Match Candidate. Score: {final_score:.1f}%")
                                    
            if best_fuzzy_match:
                s_idx, l_idx, score = best_fuzzy_match
                matched_settle_indices.add(s_idx)
                matched_ledger_indices.add(l_idx)
                
                match_data = {
                    "confidence_score": score,
                    "bank": bank_row.to_dict(),
                    "settlement": df_settle.loc[s_idx].to_dict(),
                    "ledger": df_ledger.loc[l_idx].to_dict()
                }
                
                if score >= 70:
                    fuzzy_matched.append(match_data)
                    print(f"[BUCKET ASSIGNED] {bank_utr} -> FUZZY MATCHED (Score: {score:.1f}%)")
                else:
                    needs_review.append(match_data)
                    print(f"[BUCKET ASSIGNED] {bank_utr} -> NEEDS REVIEW (Score: {score:.1f}%)")
                continue
                
            # Step 3 — No Match (Bank)
            print(f"[BUCKET ASSIGNED] {bank_utr} -> UNMATCHED (No candidate >= 40%)")
            unmatched.append({
                "source": "bank_statement",
                "record": bank_row.to_dict()
            })
            
        # Step 3 — No Match (Settlement & Ledger)
        for s_idx, s_row in df_settle.iterrows():
            if s_idx not in matched_settle_indices:
                unmatched.append({
                    "source": "settlement",
                    "record": s_row.to_dict()
                })
                
        for l_idx, l_row in df_ledger.iterrows():
            if l_idx not in matched_ledger_indices:
                unmatched.append({
                    "source": "ledger",
                    "record": l_row.to_dict()
                })

        # Step 4: AI Reasoning integration (LangGraph)
        if run_reconciliation_graph:
            patterns_to_send = {}
            
            # Fuzzy matched batching (same as before)
            for item in fuzzy_matched:
                b_amt = float(item["bank"]["amount"]) if item["bank"]["amount"] else 0.0
                s_amt = float(item["settlement"]["amount"]) if item["settlement"]["amount"] else 0.0
                
                if b_amt != s_amt and "fuzzy_fee_deducted" not in patterns_to_send:
                    patterns_to_send["fuzzy_fee_deducted"] = item
                elif b_amt == s_amt and "fuzzy_date_shifted" not in patterns_to_send:
                    patterns_to_send["fuzzy_date_shifted"] = item
            
            # Unmatched records: Send exact verified state
            for i, u in enumerate(unmatched):
                src = u["source"]
                if src == "bank_statement":
                    missing = "Settlement and Internal Ledger"
                elif src == "settlement":
                    missing = "Bank Statement and Internal Ledger"
                else:
                    missing = "Bank Statement and Settlement"
                
                context = f"Record is present in {src.replace('_', ' ').title()}, but completely missing in {missing}."
                patterns_to_send[f"unmatched_{i}"] = {
                    "unmatched_record": u["record"],
                    "source": u["source"],
                    "context": context
                }
                    
            ambiguous_input = []
            for key, val in patterns_to_send.items():
                val_copy = val.copy()
                val_copy["graph_id"] = key
                ambiguous_input.append(val_copy)
                
            reasons_dict = {}
            if ambiguous_input or fully_matched:
                # Fully matched is passed to deterministic_node
                final_state = run_reconciliation_graph(fully_matched, ambiguous_input)
                reasons_dict = {item["record_id"]: item["reason"] for item in final_state.get("reasoned_records", [])}
                
            # Apply reasons to Fuzzy
            for item in fuzzy_matched:
                b_amt = float(item["bank"]["amount"]) if item["bank"]["amount"] else 0.0
                s_amt = float(item["settlement"]["amount"]) if item["settlement"]["amount"] else 0.0
                if b_amt != s_amt:
                    item["ai_reason"] = reasons_dict.get("fuzzy_fee_deducted", "Gateway fee deduction")
                else:
                    item["ai_reason"] = reasons_dict.get("fuzzy_date_shifted", "Settlement delay")
                    
            # Apply reasons to Needs Review
            for item in needs_review:
                item["ai_reason"] = "Low confidence match, requires manual review"
                    
            # Apply reasons to Unmatched
            for i, u in enumerate(unmatched):
                reason = reasons_dict.get(f"unmatched_{i}")
                if not reason:
                    # Fallback logic if AI failed to return reason
                    reason = "Missing in other sources"
                u["ai_reason"] = reason
                
        # Calculate summary
        total_records_count = len(df_bank) + len(df_settle) + len(df_ledger)
        fully_matched_count = len(fully_matched)
        fuzzy_matched_count = len(fuzzy_matched)
        needs_review_count = len(needs_review)
        unmatched_count = len(unmatched)
        
        total_possible_triplets = total_records_count / 3
        match_rate = round(((fully_matched_count + fuzzy_matched_count + needs_review_count) / total_possible_triplets) * 100, 2) if total_possible_triplets > 0 else 0
        
        return {
            "summary": {
                "total_records": total_records_count,
                "fully_matched": fully_matched_count,
                "fuzzy_matched": fuzzy_matched_count,
                "needs_review": needs_review_count,
                "unmatched": unmatched_count,
                "match_rate_percent": match_rate
            },
            "fully_matched": fully_matched,
            "fuzzy_matched": fuzzy_matched,
            "needs_review": needs_review,
            "unmatched": unmatched
        }
    except Exception as e:
        import traceback
        return {"status": "error", "message": str(e), "trace": traceback.format_exc()}

from typing import Dict, Any

@app.post("/evaluate")
def evaluate(payload: Dict[str, Any]):
    try:
        if not os.path.exists("ground_truth.csv"):
            return {"status": "error", "message": "ground_truth.csv not found"}
            
        df_truth = pd.read_csv("ground_truth.csv")
        ground_truth = dict(zip(df_truth['group_id'], df_truth['true_category']))
        
        predicted = {}
        
        # Parse Fully Matched
        for item in payload.get("fully_matched", []):
            gid = item.get("bank", {}).get("group_id")
            if gid:
                predicted[gid] = "Fully Matched"
                
        # Parse Fuzzy Matched
        for item in payload.get("fuzzy_matched", []):
            gid = item.get("bank", {}).get("group_id")
            if gid:
                predicted[gid] = "Fuzzy Matched"
                
        # Parse Needs Review (Treated as MANUAL_REVIEW for evaluation to clear leak)
        for item in payload.get("needs_review", []):
            gid = item.get("bank", {}).get("group_id")
            if gid:
                predicted[gid] = "MANUAL_REVIEW"
                
        # Parse Unmatched
        for item in payload.get("unmatched", []):
            gid = item.get("record", {}).get("group_id")
            if gid:
                predicted[gid] = "Unmatched"
                
        categories = ["Fully Matched", "Fuzzy Matched", "Unmatched", "MANUAL_REVIEW"]
        category_stats = {cat: {"total": 0, "correct": 0} for cat in categories}
        confusion_matrix = {t: {p: 0 for p in categories} for t in categories}
        
        total = 0
        correct = 0
        fp_count = 0
        fn_count = 0
        misclassified = []
        
        for gid, true_cat in ground_truth.items():
            pred_cat = predicted.get(gid, "Unmatched") # If missing, assume unmatched
            
            total += 1
            if true_cat in category_stats:
                category_stats[true_cat]["total"] += 1
                confusion_matrix[true_cat][pred_cat] += 1
            
            if pred_cat == true_cat:
                correct += 1
                if true_cat in category_stats:
                    category_stats[true_cat]["correct"] += 1
            else:
                if pred_cat in ["Fully Matched", "Fuzzy Matched"] and true_cat == "Unmatched":
                    fp_count += 1
                elif pred_cat == "Unmatched" and true_cat in ["Fully Matched", "Fuzzy Matched"]:
                    fn_count += 1
                    
                misclassified.append({
                    "group_id": gid,
                    "expected": true_cat,
                    "predicted": pred_cat
                })
                
        cat_breakdown = {}
        for cat, stats in category_stats.items():
            cat_total = stats["total"]
            cat_acc = (stats["correct"] / cat_total * 100) if cat_total > 0 else 0
            cat_breakdown[cat] = {
                "accuracy": round(cat_acc, 2),
                "total": cat_total
            }
            
        overall_acc = (correct / total * 100) if total > 0 else 0
        
        return {
            "overall_accuracy": round(overall_acc, 2),
            "total_evaluated": total,
            "correct_predictions": correct,
            "category_breakdown": cat_breakdown,
            "confusion_matrix": confusion_matrix,
            "false_positives": fp_count,
            "false_negatives": fn_count,
            "misclassified_examples": misclassified[:5]
        }
    except Exception as e:
        import traceback
        return {"status": "error", "message": str(e), "trace": traceback.format_exc()}

@app.post("/forecast")
def forecast(payload: Dict[str, Any]):
    try:
        import json
        history_data = payload.get("history", [])
        if not history_data:
            return {"status": "error", "message": "No historical data provided"}
            
        from gemini_client import call_gemini
        
        prompt = f"""Ye pichle 30 din ka settlement data hai (dates aur amounts), is pattern ke base par agle 7 din ka expected daily inflow predict karo. Response JSON array me do: [{{"date": "YYYY-MM-DD", "predicted_amount": 1234, "confidence_note": "..."}}]
        
        Historical Data:
        {json.dumps(history_data)}
        
        Sirf JSON array return karo, koi extra text nahi.
        """
        
        forecast_result = call_gemini(prompt, is_json=True, temperature=0.2)
        
        return {
            "status": "success",
            "forecast": forecast_result
        }
    except Exception as e:
        import traceback
        return {"status": "error", "message": str(e), "trace": traceback.format_exc()}

@app.post("/ask")
def ask(payload: Dict[str, Any]):
    try:
        import json
        from gemini_client import call_gemini
        
        question = payload.get("question", "")
        context_data = payload.get("context_data", {})
        
        if not question:
            return {"status": "error", "message": "No question provided"}
            
        from collections import Counter
        
        fuzzy_reasons = []
        for item in context_data.get("fuzzy_matched", []) + context_data.get("needs_review", []):
            fuzzy_reasons.append(item.get("ai_reason", "Low confidence match"))
            
        unmatched_reasons = []
        for item in context_data.get("unmatched", []):
            unmatched_reasons.append(item.get("ai_reason", "Unmatched record"))
            
        fuzzy_counts = dict(Counter(fuzzy_reasons))
        unmatched_counts = dict(Counter(unmatched_reasons))
        
        fuzzy_summary = ", ".join([f"{k}: {v} records" for k, v in fuzzy_counts.items()])
        unmatched_summary = ", ".join([f"{k}: {v} records" for k, v in unmatched_counts.items()])
        
        reason_breakdown = f"""
        Fuzzy & Review Matches Reasons: {fuzzy_summary or 'None'}
        Unmatched Reasons: {unmatched_summary or 'None'}
        """
        
        lite_context = {
            "summary": context_data.get("summary", {}),
            "evaluation": context_data.get("evaluation", {})
        }
            
        prompt = f"""Tum ek financial analyst assistant ho. Yaha reconciliation summary hai {json.dumps(lite_context, default=str)} aur reason breakdown hai [{reason_breakdown}]. User ka sawaal ka jawab ishi breakdown ke basis pe do, specific ho, generic mat bolo.
        
        User ka sawaal: {question}
        
        Concise, helpful answer do (max 100 words), jaise ek insaan colleague jawab dega. Response plain text me hona chahiye.
        """
        
        answer = call_gemini(prompt, is_json=False, temperature=0.4)
        return {
            "status": "success",
            "answer": answer
        }
    except Exception as e:
        print("=== CHAT ASSISTANT CALL FAILED ===")
        print(f"Error type: {type(e).__name__}")
        print(f"Error message: {str(e)}")
        import traceback
        traceback.print_exc()
        print("===================================")
        return {"status": "error", "message": str(e), "trace": traceback.format_exc()}

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
