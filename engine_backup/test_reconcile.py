from main import reconcile
import json

print("\n\n====== RUNNING RECONCILIATION TEST ======")
result = reconcile()

if result.get("status") == "error":
    print("Error:", result)
else:
    summary = result.get("summary", {})
    print("\n====== FINAL RECONCILIATION SUMMARY ======")
    print(f"Total Records: {summary.get('total_records')}")
    print(f"Fully Matched: {summary.get('fully_matched')} groups")
    print(f"Fuzzy Matched: {summary.get('fuzzy_matched')} groups")
    print(f"Unmatched: {summary.get('unmatched')} records")
    print("==========================================\n")
