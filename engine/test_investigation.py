import unittest
import json
from unittest.mock import patch
from investigation_tools import InvestigationTools
from investigation_graph import run_investigation, classify_exception_node

class TestInvestigationAgent(unittest.TestCase):
    def setUp(self):
        self.bank = [
            {"source": "bank", "normalized_record": {"id": "B1", "amount": 5000, "date": "2026-08-20", "utr": "UTR123", "narration": "Test"}},
            {"source": "bank", "normalized_record": {"id": "B2", "amount": 1000, "date": "2026-08-21", "utr": "UTR456", "narration": "Test2"}},
        ]
        self.settle = [
            {"source": "settlement", "original_record": {"fee": 50}, "normalized_record": {"id": "S1", "amount": 4950, "date": "2026-08-20", "utr": "UTR123", "merchant": "Fee 50"}},
            {"source": "settlement", "original_record": {"fee": 0}, "normalized_record": {"id": "S2", "amount": 1000, "date": "2026-08-25", "utr": "UTR456", "merchant": "Test2"}},
        ]
        self.ledger = [
            {"source": "ledger", "normalized_record": {"id": "L1", "amount": 5000, "date": "2026-08-20", "utr": "UTR123", "customer": "Test"}},
            {"source": "ledger", "normalized_record": {"id": "L2", "amount": 1000, "date": "2026-08-21", "utr": "UTR456", "customer": "Test2"}},
        ]
        self.tools = InvestigationTools(self.bank, self.settle, self.ledger)

    def test_fee_mismatch_tools(self):
        # TEST 2: Gateway fee difference
        diff = self.tools.calculate_amount_difference(5000, 4950)
        self.assertEqual(diff, 50.0)
        fees = self.tools.find_related_fees(50.0)
        self.assertTrue(len(fees) > 0)
        self.assertEqual(fees[0]["normalized_record"]["id"], "S1")

    def test_settlement_delay_tools(self):
        # TEST 3 & 4: Settlement delay
        res_within = self.tools.check_settlement_timing("2026-08-20", "2026-08-21", max_days=3)
        self.assertEqual(res_within["status"], "WITHIN_TOLERANCE")
        
        res_outside = self.tools.check_settlement_timing("2026-08-21", "2026-08-25", max_days=3)
        self.assertEqual(res_outside["status"], "DELAYED")

    def test_missing_settlement_classification(self):
        # TEST 6: Missing settlement
        state = {
            "source_records": {"bank": self.bank[0]},
            "exception_type": "UNMATCHED",
            "investigation_steps": []
        }
        new_state = classify_exception_node(state)
        self.assertEqual(new_state["exception_type"], "MISSING_SETTLEMENT")

    def test_duplicate_classification(self):
        # TEST 7: Duplicate UTR
        state = {
            "source_records": {"bank": self.bank[0]},
            "exception_type": "DUPLICATE_SUSPECTED",
            "investigation_steps": []
        }
        new_state = classify_exception_node(state)
        self.assertEqual(new_state["exception_type"], "DUPLICATE_TRANSACTION")

    @patch('investigation_graph.call_gemini')
    def test_llm_unavailable_fallback(self, mock_call_gemini):
        # TEST 9: LLM unavailable -> deterministic result still available
        mock_call_gemini.side_effect = Exception("API Error")
        
        exception_group = {
            "group_id": "EXC-1",
            "status": "NEEDS_REVIEW",
            "bank": self.bank[0],
            "settlement": self.settle[0],
            "ledger": self.ledger[0]
        }
        
        result = run_investigation(exception_group, self.tools)
        self.assertEqual(result["resolution"], "UNRESOLVED")
        self.assertTrue("AI explanation unavailable" in result["root_cause"])

    @patch('investigation_graph.call_gemini')
    def test_fee_mismatch_workflow(self, mock_call_gemini):
        # Simulate LLM returning tool request then final decision
        mock_call_gemini.side_effect = [
            # First call: LLM asks for amount diff
            {"tool_calls": [{"name": "calculate_amount_difference", "args": {"amount1": 5000, "amount2": 4950}}]},
            # Second call: LLM asks for fee
            {"tool_calls": [{"name": "find_related_fees", "args": {"diff_amount": 50.0}}]},
            # Third call: LLM provides final decision
            {"final_decision": {
                "root_cause": "Gateway fee of 50 found.",
                "resolution": "AI_RESOLVED",
                "confidence": 0.95,
                "recommendation": "No action needed."
            }}
        ]
        
        exception_group = {
            "group_id": "EXC-2",
            "status": "PARTIAL_MATCH",
            "bank": self.bank[0],
            "settlement": self.settle[0],
            "ledger": self.ledger[0]
        }
        
        result = run_investigation(exception_group, self.tools)
        self.assertEqual(result["resolution"], "AI_RESOLVED")
        self.assertEqual(len(result["evidence"]), 2) # Two tool calls were made

if __name__ == '__main__':
    unittest.main()
