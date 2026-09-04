import pandas as pd
import os
import json
import time
import io
from fastapi import FastAPI, File, UploadFile, Form
from typing import Dict, Any
import uvicorn

from normalization import apply_normalization
from matcher import MultiSourceMatcher
from validation import validate_dataframe

from normalization import apply_normalization
from matcher import MultiSourceMatcher

# Import AI investigation agent
from investigation_tools import InvestigationTools
try:
    from investigation_graph import run_investigation
    from audit_logger import log_ai_decision, log_human_action, log_system_event, log_audit_event
except ImportError:
    run_investigation = None
    log_ai_decision = None
    log_human_action = None
    log_system_event = lambda *args, **kwargs: None
    log_audit_event = lambda *args, **kwargs: None

app = FastAPI(title="Finance Controller Engine", description="AI reconciliation service")

@app.get("/health")
def health_check():
    from gemini_client import check_gemini_health
    gemini_status = check_gemini_health()
    return {
        "status": "ok",
        "message": "FastAPI engine is running smoothly!",
        "gemini": gemini_status
    }

def load_data_internally():
    if not os.path.exists("bank_statement.csv"):
        raise Exception("Data files not found. Please run generate_data.py first.")
        
    df_bank = pd.read_csv("bank_statement.csv")
    df_settle = pd.read_csv("razorpay_settlements.csv")
    df_ledger = pd.read_csv("internal_ledger.csv")
    
    df_bank = df_bank.where(pd.notnull(df_bank), None)
    df_settle = df_settle.where(pd.notnull(df_settle), None)
    df_ledger = df_ledger.where(pd.notnull(df_ledger), None)    
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

def run_reconciliation_pipeline(df_bank, df_settle, df_ledger, run_id='UNKNOWN'):
    import time
    import concurrent.futures
    
    start_time = time.time()
    total_records_count = len(df_bank) + len(df_settle) + len(df_ledger)
    
    print(f"[Reconciliation] Starting pipeline for {total_records_count} records")
    
    # 1. Normalize
    norm_start = time.time()
    bank_norm, settle_norm, ledger_norm = apply_normalization(df_bank, df_settle, df_ledger)
    print(f"[Reconciliation] Normalization: {int((time.time() - norm_start)*1000)}ms")
    
    # 2. Multi-Stage Match
    match_start = time.time()
    matcher = MultiSourceMatcher(bank_norm, settle_norm, ledger_norm)
    groups = matcher.run()
    print(f"[Reconciliation] Matching (O(1) indexed): {int((time.time() - match_start)*1000)}ms")
    
    # 3. Categorize
    cat_start = time.time()
    fully_matched = []
    fuzzy_matched = []
    needs_review = []
    unmatched = []
    
    for g in groups:
        st = g["status"]
        if st == "FULLY_MATCHED": 
            fully_matched.append(g)
        elif st == "FUZZY_MATCHED": 
            fuzzy_matched.append(g)
        elif st in ["NEEDS_REVIEW", "PARTIAL_MATCH", "DUPLICATE_SUSPECTED"]: 
            needs_review.append(g)
        elif st == "UNMATCHED": 
            unmatched.append(g)
            
    # Send basic audit events (TODO: batch these for production)
    for g in fully_matched: log_audit_event("MATCH_CREATED", "SYSTEM", {"run_id": run_id, "exception_id": g.get("group_id"), "decision": g["status"]})
    for g in fuzzy_matched + needs_review + unmatched: log_audit_event("EXCEPTION_CREATED", "SYSTEM", {"run_id": run_id, "exception_id": g.get("group_id"), "decision": g["status"]})
    
    print(f"[Reconciliation] Categorization & Logging: {int((time.time() - cat_start)*1000)}ms")
        
    # 4. Fast AI Exception Investigation
    if run_investigation:
        ai_start = time.time()
        tools = InvestigationTools(bank_norm, settle_norm, ledger_norm)
        exceptions = fuzzy_matched + needs_review + unmatched
        
        print(f"[Reconciliation] Starting FAST Batched AI Investigation for {len(exceptions)} exceptions...")
        
        if exceptions:
            from reasoning import get_exception_reasons_for_patterns
            
            # 1. Deterministic evidence gathering
            patterns_dict = {}
            for exc in exceptions:
                exc_id = exc.get("group_id", "UNKNOWN")
                log_audit_event("INVESTIGATION_STARTED", "SYSTEM", {"run_id": run_id, "exception_id": exc_id})
                
                b_amt = float(exc.get("bank").get("amount") or 0) if exc.get("bank") else 0.0
                s_amt = float(exc.get("settlement").get("amount") or 0) if exc.get("settlement") else 0.0
                amt_diff = round(abs(b_amt - s_amt), 2) if b_amt and s_amt else 0.0
                
                evidence = []
                if amt_diff > 0:
                    if tools.find_related_fees(amt_diff): evidence.append("Fee matches diff")
                    if tools.find_related_taxes(amt_diff): evidence.append("Tax matches diff")
                
                exc["deterministic_evidence"] = evidence
                
                patterns_dict[exc_id] = {
                    "status": exc.get("status"),
                    "bank": exc.get("bank").get("merchant") if exc.get("bank") else None,
                    "settlement": exc.get("settlement").get("merchant") if exc.get("settlement") else None,
                    "ledger": exc.get("ledger").get("merchant") if exc.get("ledger") else None,
                    "evidence": evidence
                }
                
            # 2. Single batched LLM call
            reasons = get_exception_reasons_for_patterns(patterns_dict)
            
            # 3. Apply reasons back
            for exc in exceptions:
                exc_id = exc.get("group_id")
                reason = reasons.get(exc_id, "Requires manual review")
                
                res = "NEEDS_REVIEW"
                if "fee" in reason.lower() or "tax" in reason.lower() or exc.get("status") == "FUZZY_MATCHED":
                    res = "AI_RESOLVED"
                if "missing" in reason.lower():
                    res = "NEEDS_REVIEW"
                    
                final_state = {
                    "exception_id": exc_id,
                    "transaction_id": exc.get("bank", {}).get("id", "UNKNOWN") if exc.get("bank") else "UNKNOWN",
                    "exception_type": exc.get("status", "UNKNOWN_EXCEPTION"),
                    "root_cause": reason,
                    "resolution": res,
                    "confidence": 0.95 if res == "AI_RESOLVED" else 0.65,
                    "recommendation": "Auto-resolved by AI" if res == "AI_RESOLVED" else "Manual review required",
                    "investigation_steps": ["Deterministic evidence check", "Batched AI evaluation"],
                    "evidence": [{"tool": "batch_reasoning", "result": exc.get("deterministic_evidence")}],
                    "run_id": run_id
                }
                exc["investigation_state"] = final_state
                
                log_audit_event("INVESTIGATION_COMPLETED", "SYSTEM", {"run_id": run_id, "exception_id": exc_id})
                if log_ai_decision:
                    log_ai_decision(final_state)
                    
        print(f"[Reconciliation] AI Investigation: {int((time.time() - ai_start)*1000)}ms")
                
    end_time = time.time()
    processing_time_ms = int((end_time - start_time) * 1000)
    throughput = int(total_records_count / (end_time - start_time)) if (end_time - start_time) > 0 else 0
    print(f"[Reconciliation] TOTAL: {processing_time_ms}ms")
    
    total_groups = len(groups)
    match_rate = round((len(fully_matched) + len(fuzzy_matched)) / total_groups * 100, 2) if total_groups > 0 else 0
    
    return {
        "summary": {
            "total_records": total_records_count,
            "total_groups": total_groups,
            "fully_matched": len(fully_matched),
            "fuzzy_matched": len(fuzzy_matched),
            "needs_review": len(needs_review),
            "unmatched": len(unmatched),
            "match_rate_percent": match_rate,
            "processing_time_ms": processing_time_ms,
            "throughput_per_sec": throughput
        },
        "fully_matched": fully_matched,
        "fuzzy_matched": fuzzy_matched,
        "needs_review": needs_review,
        "unmatched": unmatched
    }

@app.post("/exceptions/resolve")
def resolve_exception(payload: Dict[str, Any]):
    try:
        exc_id = payload.get("exception_id")
        txn_id = payload.get("transaction_id", "UNKNOWN")
        action = payload.get("action")
        prev_status = payload.get("previous_status", "UNKNOWN")
        final_status = payload.get("final_status", action)
        reason = payload.get("reason", "")
        actor_id = payload.get("actor_id", "Unknown")
        actor_role = payload.get("actor_role", "REVIEWER")
        notes = payload.get("notes", None)
        ai_decision = payload.get("ai_decision", prev_status)
        run_id = payload.get("runId", payload.get("run_id", "UNKNOWN"))
        
        if actor_role == "VIEWER":
            return {"status": "error", "message": "Unauthorized action"}
            
        if prev_status in ["HUMAN_CONFIRMED", "REJECTED", "VALID_DIFFERENCE", "OVERRIDDEN"] and action not in ["Add Note", "Reopen"]:
            return {"status": "error", "message": "Case already reviewed"}
            
        if log_human_action:
            log_human_action(exc_id, txn_id, action, prev_status, final_status, reason, actor_id, actor_role, notes, ai_decision, run_id)
            
        return {"status": "success", "message": "Action logged successfully."}
    except Exception as e:
        import traceback
        return {"status": "error", "message": str(e), "trace": traceback.format_exc()}

@app.post("/reconcile")
def reconcile():
    try:
        df_bank, df_settle, df_ledger = load_data_internally()
        return run_reconciliation_pipeline(df_bank, df_settle, df_ledger, 'test-run')
    except Exception as e:
        import traceback
        return {"status": "error", "message": str(e), "trace": traceback.format_exc()}

def read_file(file_obj):
    if not file_obj: return pd.DataFrame()
    content = file_obj.file.read()
    if not content: return pd.DataFrame()
    if file_obj.filename.endswith('.json'):
        return pd.read_json(io.BytesIO(content))
    else:
        return pd.read_csv(io.BytesIO(content))

@app.post("/validate")
async def validate_data(
    bank_file: UploadFile = File(None),
    settle_file: UploadFile = File(None),
    ledger_file: UploadFile = File(None)
):
    try:
        df_bank = read_file(bank_file)
        df_settle = read_file(settle_file)
        df_ledger = read_file(ledger_file)
        
        df_bank = df_bank.where(pd.notnull(df_bank), None)
        df_settle = df_settle.where(pd.notnull(df_settle), None)
        df_ledger = df_ledger.where(pd.notnull(df_ledger), None)
        log_system_event("DATASET_UPLOADED", dataset_id, {"bank_rows": len(df_bank), "settle_rows": len(df_settle), "ledger_rows": len(df_ledger)})

        
        val_bank = validate_dataframe(df_bank, "bank")
        val_settle = validate_dataframe(df_settle, "settlement")
        val_ledger = validate_dataframe(df_ledger, "ledger")
        
        all_errors = val_bank["errors"] + val_settle["errors"] + val_ledger["errors"]
        
        return {
            "valid": len(all_errors) == 0,
            "sources": {
                "bank": val_bank,
                "settlement": val_settle,
                "ledger": val_ledger
            },
            "errors": all_errors[:100]
        }
    except Exception as e:
        import traceback
        return {"status": "error", "message": str(e), "trace": traceback.format_exc()}

@app.post("/upload-and-reconcile")
async def upload_and_reconcile(
    dataset_id: str = Form(...),
    exclude_invalid: bool = Form(False),
    bank_file: UploadFile = File(None),
    settle_file: UploadFile = File(None),
    ledger_file: UploadFile = File(None)
):
    try:
        df_bank = read_file(bank_file)
        df_settle = read_file(settle_file)
        df_ledger = read_file(ledger_file)
        
        df_bank = df_bank.where(pd.notnull(df_bank), None)
        df_settle = df_settle.where(pd.notnull(df_settle), None)
        df_ledger = df_ledger.where(pd.notnull(df_ledger), None)
        log_system_event("DATASET_UPLOADED", dataset_id, {"bank_rows": len(df_bank), "settle_rows": len(df_settle), "ledger_rows": len(df_ledger)})

        
        val_bank = validate_dataframe(df_bank, "bank")
        val_settle = validate_dataframe(df_settle, "settlement")
        val_ledger = validate_dataframe(df_ledger, "ledger")
        
        if exclude_invalid:
            # We can re-validate or just use the logic to drop invalid rows
            # A simple way without modifying validation.py is to just drop by index
            # Wait, validate_dataframe doesn't return valid_indices yet. We'll modify it next.
            if "valid_indices" in val_bank: df_bank = df_bank.iloc[val_bank["valid_indices"]]
            if "valid_indices" in val_settle: df_settle = df_settle.iloc[val_settle["valid_indices"]]
            if "valid_indices" in val_ledger: df_ledger = df_ledger.iloc[val_ledger["valid_indices"]]

        # Run core matching
        log_system_event("RECONCILIATION_STARTED", dataset_id)
        result = run_reconciliation_pipeline(df_bank, df_settle, df_ledger, dataset_id)
        log_system_event("RECONCILIATION_COMPLETED", dataset_id, {"summary": result.get("summary", {})})

        
        # Inject metadata and validation
        result["dataset_id"] = dataset_id
        result["data_quality"] = {
            "bank": val_bank,
            "settlement": val_settle,
            "ledger": val_ledger
        }
        
        return result
    except Exception as e:
        import traceback
        return {"status": "error", "message": str(e), "trace": traceback.format_exc()}

@app.post("/evaluate")
def evaluate(payload: Dict[str, Any]):
    try:
        if not os.path.exists("ground_truth.json"):
            return {"status": "error", "message": "ground_truth.json not found"}
            
        with open("ground_truth.json", "r") as f:
            truth_data = json.load(f)
            
        # Build mapping from any source ID to the expected status
        # Since prediction gives us group_ids that don't match the truth's group_id, we map by record id.
        expected_status_by_rec = {}
        expected_item_by_rec = {}
        for item in truth_data:
            expected = item["expected_status"]
            recs = item["record_ids"]
            for v in recs.values():
                if v: 
                    expected_status_by_rec[v] = expected
                    expected_item_by_rec[v] = item
                
        # Now map prediction
        predicted_by_rec = {}
        full_group_by_rec = {}
        
        def index_group(group_list, default_status):
            for g in group_list:
                status = g.get("status", default_status)
                for k in ["bank", "settlement", "ledger"]:
                    if g.get(k): 
                        predicted_by_rec[g[k]["id"]] = status
                        full_group_by_rec[g[k]["id"]] = g
                
        index_group(payload.get("fully_matched", []), "FULLY_MATCHED")
        index_group(payload.get("fuzzy_matched", []), "FUZZY_MATCHED")
        index_group(payload.get("needs_review", []), "NEEDS_REVIEW")
        index_group(payload.get("unmatched", []), "UNMATCHED")
        
        categories = ["FULLY_MATCHED", "FUZZY_MATCHED", "NEEDS_REVIEW", "PARTIAL_MATCH", "DUPLICATE_SUSPECTED", "UNMATCHED"]
        
        tp = {c: 0 for c in categories}
        fp = {c: 0 for c in categories}
        fn = {c: 0 for c in categories}
        
        confusion_matrix = {c: {c2: 0 for c2 in categories} for c in categories}
        
        total = 0
        correct = 0
        misclassified = []
        high_confidence_errors = 0
        high_confidence_total = 0
        auto_resolved_total = 0
        auto_resolved_incorrect = 0
        
        # Evaluate per ground truth item
        # Since an item consists of up to 3 records, we take the consensus predicted status of the item.
        for item in truth_data:
            expected = item["expected_status"]
            recs = item["record_ids"]
            preds = [predicted_by_rec.get(v, "UNMATCHED") for v in recs.values() if v]
            if not preds: continue
            
            # Find the actual group data to check confidence and AI resolution
            first_rec = next((v for v in recs.values() if v), None)
            group_data = full_group_by_rec.get(first_rec, {})
            
            from collections import Counter
            pred_cat = Counter(preds).most_common(1)[0][0]
            
            total += 1
            if expected not in confusion_matrix: confusion_matrix[expected] = {c: 0 for c in categories}
            if pred_cat not in confusion_matrix[expected]: confusion_matrix[expected][pred_cat] = 0
            
            confusion_matrix[expected][pred_cat] += 1
            
            inv_state = group_data.get("investigation_state", {})
            confidence = inv_state.get("confidence", 0.0) if inv_state else (100.0 if pred_cat == "FULLY_MATCHED" else 0.0)
            is_high_conf = confidence >= 90.0
            is_auto_resolved = inv_state.get("resolution") == "AI_RESOLVED" or pred_cat == "FULLY_MATCHED"
            
            if is_high_conf:
                high_confidence_total += 1
                
            if is_auto_resolved:
                auto_resolved_total += 1
            
            if pred_cat == expected:
                correct += 1
                tp[expected] += 1
            else:
                fp[pred_cat] += 1
                fn[expected] += 1
                
                if is_high_conf:
                    high_confidence_errors += 1
                if is_auto_resolved:
                    auto_resolved_incorrect += 1
                    
                misclassified.append({
                    "group_id": group_data.get("group_id", "Unknown"),
                    "expected": expected,
                    "expected_exception": item.get("expected_exception_type", "NONE"),
                    "predicted": pred_cat,
                    "confidence": confidence,
                    "resolution": inv_state.get("resolution", "NONE")
                })
                
        def safe_div(n, d):
            return round((n / d) * 100, 2) if d > 0 else 'N/A'
            
        def safe_f1(p, r):
            if p == 'N/A' or r == 'N/A' or (p + r) == 0: return 'N/A'
            return round(2 * p * r / (p + r), 2)
                
        cat_breakdown = {}
        for cat in categories:
            t_tp = tp[cat]
            t_fp = fp[cat]
            t_fn = fn[cat]
            
            precision = safe_div(t_tp, t_tp + t_fp)
            recall = safe_div(t_tp, t_tp + t_fn)
            f1 = safe_f1(precision, recall) if precision != 'N/A' else 'N/A'
            
            cat_breakdown[cat] = {
                "precision": precision,
                "recall": recall,
                "f1": f1,
                "total_expected": t_tp + t_fn
            }
            
        overall_acc = safe_div(correct, total)
        
        # Calculate Macro metrics (average of all valid categories)
        valid_p = [cat_breakdown[c]["precision"] for c in categories if cat_breakdown[c]["precision"] != 'N/A']
        valid_r = [cat_breakdown[c]["recall"] for c in categories if cat_breakdown[c]["recall"] != 'N/A']
        macro_precision = round(sum(valid_p) / len(valid_p), 2) if valid_p else 'N/A'
        macro_recall = round(sum(valid_r) / len(valid_r), 2) if valid_r else 'N/A'
        macro_f1 = safe_f1(macro_precision, macro_recall) if macro_precision != 'N/A' else 'N/A'
        
        high_conf_error_rate = safe_div(high_confidence_errors, high_confidence_total)
        auto_res_error_rate = safe_div(auto_resolved_incorrect, auto_resolved_total)
        
        # Include summary processing metrics if available in payload
        summary = payload.get("summary", {})
        
        return {
            "overall_accuracy": overall_acc,
            "macro_precision": macro_precision,
            "macro_recall": macro_recall,
            "macro_f1": macro_f1,
            "total_evaluated": total,
            "correct_predictions": correct,
            "incorrect_predictions": total - correct,
            "high_confidence_error_rate": high_conf_error_rate,
            "auto_resolution_error_rate": auto_res_error_rate,
            "confusion_matrix": confusion_matrix,
            "category_breakdown": cat_breakdown,
            "misclassified_examples": misclassified,
            "performance": {
                "throughput_per_sec": summary.get("throughput_per_sec", "N/A"),
                "processing_time_ms": summary.get("processing_time_ms", "N/A"),
                "match_rate_percent": summary.get("match_rate_percent", "N/A")
            }
        }
    except Exception as e:
        import traceback
        return {"status": "error", "message": str(e), "trace": traceback.format_exc()}

from forecast import generate_forecast

@app.post("/forecast")
def forecast(payload: Dict[str, Any]):
    try:
        groups = []
        groups.extend(payload.get("fully_matched", []))
        groups.extend(payload.get("fuzzy_matched", []))
        groups.extend(payload.get("needs_review", []))
        groups.extend(payload.get("unmatched", []))
        
        config = payload.get("config", {})
        result = generate_forecast(groups, config)
        
        return {
            "status": "success",
            "forecast": result
        }
    except Exception as e:
        import traceback
        return {"status": "error", "message": str(e), "trace": traceback.format_exc()}

@app.post("/ask")
def ask(payload: Dict[str, Any]):
    try:
        import json
        from gemini_client import call_gemini, GeminiPermanentError
        
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
            "evaluation": context_data.get("evaluation", {}),
            "forecast": context_data.get("forecast", {}),
            "audit_metrics": context_data.get("audit_metrics", {}),
            "top_exceptions": context_data.get("top_exceptions", []),
            "specific_transaction": context_data.get("specific_transaction", {})
        }
            
        prompt = f"""You are an Executive AI Finance Copilot.
You have the following structured backend data representing the current finance reconciliation run.

DATA:
{json.dumps(lite_context, default=str)}

REASON BREAKDOWN: 
[{reason_breakdown}]

USER QUESTION: {question}

CRITICAL RULES:
1. NEVER invent financial facts, amounts, dates, IDs, or audit events.
2. If the user asks for information completely absent from the DATA, state you don't have enough evidence. But if partial or summarized data is available (e.g., you have top exceptions instead of all exceptions), use the available DATA to provide the best possible answer.
3. If multiple interpretations exist, explain the ambiguity.
4. Use the `forecast` object for cash position/forecast questions. Use `audit_metrics` for AI performance/human review rates.
5. If the user asks about a specific transaction (e.g. TXN-1045) and it is in `specific_transaction`, explain its state based on the evidence.
6. Keep your final answer concise, professional, and grounded in the data. Provide evidence/source where appropriate.

Format your response as a direct, clear answer. Do not include your internal reasoning steps in the output.
"""
        
        answer = call_gemini(prompt, is_json=False, temperature=0.1)
        return {
            "status": "success",
            "answer": answer
        }
    except GeminiPermanentError as e:
        return {
            "status": "error",
            "message": "AI Copilot is temporarily unavailable due to a configuration issue. Your reconciliation data and evidence are still fully available for manual review."
        }
    except Exception as e:
        return {
            "status": "error",
            "message": "AI investigation is temporarily unavailable. The transaction evidence is still available for manual review."
        }

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
