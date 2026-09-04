import unittest
import json
import os
from unittest.mock import patch, MagicMock

# Import the FastAPI app directly for testing if using TestClient
from fastapi.testclient import TestClient
from main import app
import audit_logger

client = TestClient(app)

class TestReviewWorkflow(unittest.TestCase):
    
    def setUp(self):
        # Ensure a clean log file
        if os.path.exists("audit_log.jsonl"):
            os.rename("audit_log.jsonl", "audit_log.jsonl.bak")
            
    def tearDown(self):
        if os.path.exists("audit_log.jsonl"):
            os.remove("audit_log.jsonl")
        if os.path.exists("audit_log.jsonl.bak"):
            os.rename("audit_log.jsonl.bak", "audit_log.jsonl")

    def test_approve_ai_resolution(self):
        payload = {
            "exception_id": "EXC-123",
            "transaction_id": "TXN-456",
            "action": "Accept",
            "previous_status": "AI_RESOLVED",
            "final_status": "HUMAN_CONFIRMED",
            "reason": "Looks good",
            "actor_id": "user_123",
            "actor_role": "REVIEWER"
        }
        response = client.post("/exceptions/resolve", json=payload)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "success")
        
        # Verify Audit Log
        with open("audit_log.jsonl", "r") as f:
            logs = [json.loads(line) for line in f]
            
        self.assertTrue(len(logs) >= 1)
        last_log = logs[-1]
        self.assertEqual(last_log["event_type"], "HUMAN_ACCEPT")
        self.assertEqual(last_log["actor_role"], "REVIEWER")
        self.assertEqual(last_log["final_status"], "HUMAN_CONFIRMED")
        self.assertEqual(last_log["human_reason"], "Looks good")

    def test_override_decision(self):
        payload = {
            "exception_id": "EXC-999",
            "transaction_id": "TXN-000",
            "action": "Override",
            "previous_status": "NEEDS_REVIEW",
            "final_status": "VALID_DIFFERENCE",
            "reason": "Missing gateway fee",
            "actor_id": "user_456",
            "actor_role": "ADMIN"
        }
        response = client.post("/exceptions/resolve", json=payload)
        self.assertEqual(response.status_code, 200)
        
        # Verify Audit Log
        with open("audit_log.jsonl", "r") as f:
            lines = f.readlines()
            last_log = json.loads(lines[-1])
            
        self.assertEqual(last_log["event_type"], "HUMAN_OVERRIDE")
        self.assertEqual(last_log["actor_role"], "ADMIN")
        self.assertEqual(last_log["final_status"], "VALID_DIFFERENCE")
        self.assertEqual(last_log["human_reason"], "Missing gateway fee")
        
    def test_manual_match_selection(self):
        payload = {
            "exception_id": "EXC-DUP",
            "transaction_id": "TXN-DUP1",
            "action": "Manual Match",
            "previous_status": "DUPLICATE_SUSPECTED",
            "final_status": "HUMAN_CONFIRMED",
            "reason": "Matched to TXN-DUP2",
            "actor_id": "user_123",
            "actor_role": "REVIEWER"
        }
        response = client.post("/exceptions/resolve", json=payload)
        self.assertEqual(response.status_code, 200)
        
        # Verify Audit Log
        with open("audit_log.jsonl", "r") as f:
            lines = f.readlines()
            last_log = json.loads(lines[-1])
            
        self.assertEqual(last_log["event_type"], "HUMAN_MANUAL_MATCH")
        self.assertEqual(last_log["final_status"], "HUMAN_CONFIRMED")
        self.assertTrue("Matched to" in last_log["human_reason"])

if __name__ == '__main__':
    unittest.main()
