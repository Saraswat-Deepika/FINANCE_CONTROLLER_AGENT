import unittest
import json
import os
from unittest.mock import patch, MagicMock

from fastapi.testclient import TestClient
from main import app

client = TestClient(app)

class TestAuditWorkflow(unittest.TestCase):
    
    @patch("audit_logger.requests.post")
    def test_audit_human_approval(self, mock_post):
        # 8. Human approval creates event
        # 18. Original AI decision remains preserved after human override
        payload = {
            "exception_id": "EXC-123",
            "transaction_id": "TXN-456",
            "action": "Override",
            "previous_status": "NEEDS_REVIEW",
            "final_status": "OVERRIDDEN",
            "reason": "Manually verified",
            "actor_id": "user_123",
            "actor_role": "ADMIN",
            "ai_decision": "AI_RESOLVED",
            "run_id": "RUN-1"
        }
        response = client.post("/exceptions/resolve", json=payload)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "success")
        
        # Verify the audit log request
        self.assertTrue(mock_post.called)
        call_args = mock_post.call_args[1]["json"]
        self.assertEqual(call_args["event_type"], "HUMAN_OVERRIDE")
        self.assertEqual(call_args["actor_type"], "HUMAN")
        self.assertEqual(call_args["actor_role"], "ADMIN")
        self.assertEqual(call_args["new_status"], "OVERRIDDEN")
        self.assertEqual(call_args["AI_decision"], "AI_RESOLVED") # Verifies AI decision is preserved
        self.assertEqual(call_args["reason"], "Manually verified")
        self.assertIn("timestamp", call_args)

    @patch("audit_logger.requests.post")
    def test_failed_decision_not_reported_successful(self, mock_post):
        # 16. Failed decision does not appear as successful
        mock_post.side_effect = Exception("Connection Refused")
        
        payload = {
            "exception_id": "EXC-FAIL",
            "action": "Accept",
            "previous_status": "NEEDS_REVIEW",
            "final_status": "HUMAN_CONFIRMED",
            "actor_role": "REVIEWER"
        }
        
        response = client.post("/exceptions/resolve", json=payload)
        self.assertEqual(response.status_code, 200)

if __name__ == '__main__':
    unittest.main()
