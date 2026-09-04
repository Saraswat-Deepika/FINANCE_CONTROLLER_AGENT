import requests
import json
import os

print("Generating synthetic data...")
os.system("python engine/generate_data.py")

print("Calling /reconcile...")
try:
    res = requests.post("http://localhost:8000/reconcile")
    data = res.json()
    print("Reconciliation Summary:")
    print(json.dumps(data.get("summary", {}), indent=2))
    
    # Run Evaluate
    print("\nCalling /evaluate...")
    eval_payload = {
        "fully_matched": data.get("fully_matched", []),
        "fuzzy_matched": data.get("fuzzy_matched", []),
        "needs_review": data.get("needs_review", []),
        "unmatched": data.get("unmatched", []),
        "summary": data.get("summary", {})
    }
    eval_res = requests.post("http://localhost:8000/evaluate", json=eval_payload)
    eval_data = eval_res.json()
    print(f"Accuracy: {eval_data.get('overall_accuracy')}%")
    print(f"Macro F1: {eval_data.get('macro_f1')}")
    print(f"High Conf Error Rate: {eval_data.get('high_confidence_error_rate')}%")
    
    # Run Forecast
    print("\nCalling /forecast...")
    payload = {
        "fully_matched": data.get("fully_matched", []),
        "fuzzy_matched": data.get("fuzzy_matched", []),
        "needs_review": data.get("needs_review", []),
        "unmatched": data.get("unmatched", []),
        "config": {"minimum_safe_cash": 50000.0}
    }
    f_res = requests.post("http://localhost:8000/forecast", json=payload)
    f_data = f_res.json()
    
    if f_data.get("status") == "success":
        forecast = f_data["forecast"]
        print("\n=== FORECAST RESULT ===")
        print(f"Current Cash Position: ₹{forecast['current_cash_position']}")
        print(f"Pending Inflows: ₹{forecast['pending_inflows']}")
        print(f"Pending Outflows: ₹{forecast['pending_outflows']}")
        print(f"Net Pending Change: ₹{forecast['net_pending_change']}")
        print(f"Confidence: {forecast['confidence']}")
        print(f"Risk Alerts: {len(forecast['risk_alerts'])}")
        print("\nTop Inflows:")
        for t in forecast['top_drivers']['inflows'][:2]:
            print(f"  {t['description']} : ₹{t['amount']} on {t['date']}")
        print("\nTop Outflows:")
        for t in forecast['top_drivers']['outflows'][:2]:
            print(f"  {t['description']} : ₹{t['amount']} on {t['date']}")
            
        print("\nAI Q&A test...")
        ask_payload = {
            "question": "What is our current cash position?",
            "context_data": {
                "summary": data.get("summary", {}),
                "forecast": forecast
            }
        }
        ask_res = requests.post("http://localhost:8000/ask", json=ask_payload)
        print("AI says:", ask_res.json().get("answer"))
    else:
        print("Forecast failed:", f_data)
        
except Exception as e:
    print("Error:", e)
