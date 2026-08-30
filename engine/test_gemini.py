from reasoning import get_exception_reasons_for_patterns

test_data = {
    "test_pattern_1": [
        {"source": "bank", "amount": 100, "date": "2023-01-01"},
        {"source": "settlement", "amount": 98, "date": "2023-01-02"}
    ]
}

print("Running test...")
result = get_exception_reasons_for_patterns(test_data)
print("\nFinal Result:", result)
