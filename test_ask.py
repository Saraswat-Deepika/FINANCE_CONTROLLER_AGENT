import sys
sys.path.append('c:\\Users\\Deepika\\OneDrive\\Desktop\\FINANCE_CONTROLLER_AGENT\\engine')
from main import ask

payload = {
    "question": "what's causing most fuzzy matches?",
    "context_data": {
        "summary": {"total": 100},
        "fuzzy_matched": [
            {"ai_reason": "Gateway fee deduction"},
            {"ai_reason": "Gateway fee deduction"},
            {"ai_reason": "Gateway fee deduction"},
            {"ai_reason": "Settlement delay"}
        ],
        "needs_review": [
            {"ai_reason": "Low confidence match, requires manual review"},
            {"ai_reason": "Low confidence match, requires manual review"}
        ],
        "unmatched": [
            {"ai_reason": "Record missing from other sources"}
        ]
    }
}

result = ask(payload)
print("\n--- CHAT ASSISTANT ANSWER ---")
print(result["answer"])
print("-----------------------------")
