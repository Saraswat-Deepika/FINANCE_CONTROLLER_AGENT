"""
Comprehensive tests for the centralized Gemini Service.

Tests cover:
  1. Valid request (mocked success)
  2. Invalid API key → permanent error, no retry
  3. Model not found (404) → permanent error, no retry
  4. Rate limit (429) → retryable with backoff
  5. Server error (5xx) → retryable
  6. Malformed AI response → safe fallback
  7. AI unavailable during investigation → no fake resolution
  8. AI Copilot with valid data (mocked)
  9. AI Copilot with missing data
  10. Error classification correctness
"""

import unittest
import json
from unittest.mock import patch, MagicMock, PropertyMock

# Import the service
from gemini_client import (
    call_gemini,
    GeminiPermanentError,
    GeminiRetryableError,
    _classify_error,
    _extract_retry_delay,
    _parse_json_response,
    check_gemini_health,
    GEMINI_MODEL,
)


class TestErrorClassification(unittest.TestCase):
    """TEST 10: Error classification correctness."""

    def test_404_is_permanent(self):
        err = Exception("404 NOT_FOUND. model not found")
        classified = _classify_error(err)
        self.assertIsInstance(classified, GeminiPermanentError)

    def test_401_is_permanent(self):
        err = Exception("401 UNAUTHENTICATED. Invalid API key")
        classified = _classify_error(err)
        self.assertIsInstance(classified, GeminiPermanentError)

    def test_400_is_permanent(self):
        err = Exception("400 INVALID_ARGUMENT BAD_REQUEST")
        classified = _classify_error(err)
        self.assertIsInstance(classified, GeminiPermanentError)

    def test_429_is_retryable(self):
        err = Exception("429 RESOURCE_EXHAUSTED. Quota exceeded")
        classified = _classify_error(err)
        self.assertIsInstance(classified, GeminiRetryableError)

    def test_500_is_retryable(self):
        err = Exception("500 INTERNAL server error")
        classified = _classify_error(err)
        self.assertIsInstance(classified, GeminiRetryableError)

    def test_503_is_retryable(self):
        err = Exception("503 UNAVAILABLE")
        classified = _classify_error(err)
        self.assertIsInstance(classified, GeminiRetryableError)

    def test_network_timeout_is_retryable(self):
        err = Exception("Connection timeout to server")
        classified = _classify_error(err)
        self.assertIsInstance(classified, GeminiRetryableError)

    def test_unknown_is_retryable(self):
        err = Exception("Something completely unknown happened")
        classified = _classify_error(err)
        self.assertIsInstance(classified, GeminiRetryableError)


class TestRetryDelayExtraction(unittest.TestCase):
    """Test extraction of retry delay from API error messages."""

    def test_extract_from_retry_delay_field(self):
        msg = "{'retryDelay': '29s'}"
        self.assertEqual(_extract_retry_delay(msg), 29)

    def test_extract_from_retry_in_text(self):
        msg = "Please retry in 31.497310293s."
        self.assertEqual(_extract_retry_delay(msg), 32)  # Rounded up

    def test_no_delay_found(self):
        msg = "Some random error message"
        self.assertIsNone(_extract_retry_delay(msg))


class TestJsonParsing(unittest.TestCase):
    """TEST 6: Malformed AI response → safe fallback."""

    def test_valid_json_object(self):
        result = _parse_json_response('{"key": "value"}')
        self.assertEqual(result, {"key": "value"})

    def test_valid_json_array(self):
        result = _parse_json_response('[{"id": 1}]')
        self.assertEqual(result, [{"id": 1}])

    def test_json_with_markdown_fences(self):
        result = _parse_json_response('```json\n{"key": "value"}\n```')
        self.assertEqual(result, {"key": "value"})

    def test_json_with_surrounding_text(self):
        result = _parse_json_response('Here is the result: {"key": "value"} end')
        self.assertEqual(result, {"key": "value"})

    def test_completely_invalid_json(self):
        with self.assertRaises(ValueError):
            _parse_json_response("This is not JSON at all")

    def test_empty_string(self):
        with self.assertRaises(ValueError):
            _parse_json_response("")


class TestCallGeminiPermanentErrors(unittest.TestCase):
    """TEST 2 & 3: Permanent errors should NOT retry."""

    @patch('gemini_client._client')
    def test_404_model_not_found_no_retry(self, mock_client):
        """TEST 3: 404 should fail immediately, not retry 3 times."""
        mock_client.models.generate_content.side_effect = Exception(
            "404 NOT_FOUND. This model models/gemini-2.0-flash is no longer available."
        )
        
        with self.assertRaises(GeminiPermanentError) as ctx:
            call_gemini("test prompt")
        
        self.assertIn("CONFIG ERROR", str(ctx.exception))
        # Should only be called ONCE — no retries for 404
        self.assertEqual(mock_client.models.generate_content.call_count, 1)

    @patch('gemini_client._client')
    def test_401_invalid_key_no_retry(self, mock_client):
        """TEST 2: Invalid API key should fail immediately."""
        mock_client.models.generate_content.side_effect = Exception(
            "401 UNAUTHENTICATED. Invalid API key"
        )
        
        with self.assertRaises(GeminiPermanentError) as ctx:
            call_gemini("test prompt")
        
        self.assertIn("CONFIG ERROR", str(ctx.exception))
        self.assertEqual(mock_client.models.generate_content.call_count, 1)


class TestCallGeminiRetryableErrors(unittest.TestCase):
    """TEST 4 & 5: Retryable errors should retry with backoff."""

    @patch('gemini_client.time.sleep')  # Mock sleep to speed up tests
    @patch('gemini_client._client')
    def test_429_rate_limit_retries(self, mock_client, mock_sleep):
        """TEST 4: 429 should retry up to MAX_RETRIES times."""
        mock_client.models.generate_content.side_effect = Exception(
            "429 RESOURCE_EXHAUSTED. Quota exceeded. retryDelay': '4s'"
        )
        
        with self.assertRaises(GeminiRetryableError):
            call_gemini("test prompt")
        
        # Should be called MAX_RETRIES times (3)
        self.assertEqual(mock_client.models.generate_content.call_count, 3)

    @patch('gemini_client.time.sleep')
    @patch('gemini_client._client')
    def test_500_server_error_retries(self, mock_client, mock_sleep):
        """TEST 5: 500 should retry."""
        mock_client.models.generate_content.side_effect = Exception(
            "500 INTERNAL server error"
        )
        
        with self.assertRaises(GeminiRetryableError):
            call_gemini("test prompt")
        
        self.assertEqual(mock_client.models.generate_content.call_count, 3)

    @patch('gemini_client.time.sleep')
    @patch('gemini_client._client')
    def test_retry_then_success(self, mock_client, mock_sleep):
        """Rate limit on first try, success on second."""
        mock_response = MagicMock()
        mock_response.text = "Hello world"
        
        mock_client.models.generate_content.side_effect = [
            Exception("429 RESOURCE_EXHAUSTED. retryDelay': '4s'"),
            mock_response
        ]
        
        result = call_gemini("test prompt", is_json=False)
        self.assertEqual(result, "Hello world")
        self.assertEqual(mock_client.models.generate_content.call_count, 2)


class TestCallGeminiSuccess(unittest.TestCase):
    """TEST 1: Valid Gemini request."""

    @patch('gemini_client._client')
    def test_successful_text_response(self, mock_client):
        mock_response = MagicMock()
        mock_response.text = "  Test Successful  "
        mock_client.models.generate_content.return_value = mock_response
        
        result = call_gemini("Hello", is_json=False)
        self.assertEqual(result, "Test Successful")

    @patch('gemini_client._client')
    def test_successful_json_response(self, mock_client):
        mock_response = MagicMock()
        mock_response.text = '{"root_cause": "Fee deduction", "confidence": 0.95}'
        mock_client.models.generate_content.return_value = mock_response
        
        result = call_gemini("Analyze this", is_json=True)
        self.assertEqual(result["root_cause"], "Fee deduction")
        self.assertEqual(result["confidence"], 0.95)


class TestCallGeminiMalformedResponse(unittest.TestCase):
    """TEST 6: Malformed response handling."""

    @patch('gemini_client.time.sleep')
    @patch('gemini_client._client')
    def test_malformed_json_raises(self, mock_client, mock_sleep):
        """Malformed JSON should raise after retries (it's a ValueError wrapped in retries)."""
        mock_response = MagicMock()
        mock_response.text = "This is not valid JSON"
        mock_client.models.generate_content.return_value = mock_response
        
        # When is_json=True but response isn't parseable, it should raise
        with self.assertRaises(Exception):
            call_gemini("test", is_json=True)


class TestNoClientConfigured(unittest.TestCase):
    """Test behavior when no API key is set."""

    @patch('gemini_client._client', None)
    def test_no_client_raises_permanent_error(self):
        with self.assertRaises(GeminiPermanentError) as ctx:
            call_gemini("test")
        self.assertIn("API key missing", str(ctx.exception))


class TestInvestigationWithAIUnavailable(unittest.TestCase):
    """TEST 7: AI unavailable during exception investigation."""

    def setUp(self):
        from investigation_tools import InvestigationTools
        self.bank = [
            {"source": "bank", "normalized_record": {"id": "B1", "amount": 5000, "date": "2026-08-20", "utr": "UTR123", "narration": "Test"}},
        ]
        self.settle = [
            {"source": "settlement", "original_record": {"fee": 50}, "normalized_record": {"id": "S1", "amount": 4950, "date": "2026-08-20", "utr": "UTR123", "merchant": "Fee 50"}},
        ]
        self.ledger = [
            {"source": "ledger", "normalized_record": {"id": "L1", "amount": 5000, "date": "2026-08-20", "utr": "UTR123", "customer": "Test"}},
        ]
        self.tools = InvestigationTools(self.bank, self.settle, self.ledger)

    @patch('investigation_graph.call_gemini')
    def test_permanent_error_returns_unresolved(self, mock_gemini):
        """When Gemini has a permanent error, investigation should return UNRESOLVED with evidence."""
        from investigation_graph import run_investigation
        mock_gemini.side_effect = GeminiPermanentError("Model not found")
        
        exception_group = {
            "group_id": "EXC-TEST",
            "status": "NEEDS_REVIEW",
            "bank": self.bank[0],
            "settlement": self.settle[0],
            "ledger": self.ledger[0]
        }
        
        result = run_investigation(exception_group, self.tools)
        self.assertEqual(result["resolution"], "UNRESOLVED")
        self.assertIn("configuration error", result["root_cause"].lower())
        # The exception should NOT have a fake resolution
        self.assertEqual(result["confidence"], 0.0)

    @patch('investigation_graph.call_gemini')
    def test_retryable_error_returns_unresolved(self, mock_gemini):
        """When Gemini is temporarily unavailable, investigation should return UNRESOLVED."""
        from investigation_graph import run_investigation
        mock_gemini.side_effect = Exception("429 RESOURCE_EXHAUSTED")
        
        exception_group = {
            "group_id": "EXC-TEST2",
            "status": "FUZZY_MATCHED",
            "bank": self.bank[0],
            "settlement": self.settle[0],
        }
        
        result = run_investigation(exception_group, self.tools)
        self.assertEqual(result["resolution"], "UNRESOLVED")
        self.assertEqual(result["confidence"], 0.0)


class TestCopilotErrorHandling(unittest.TestCase):
    """TEST 8 & 9: AI Copilot behavior."""

    def test_copilot_missing_question(self):
        """Copilot should return error for empty question."""
        from fastapi.testclient import TestClient
        from main import app
        client = TestClient(app)
        
        response = client.post("/ask", json={"question": "", "context_data": {}})
        data = response.json()
        self.assertEqual(data["status"], "error")
        self.assertIn("No question", data["message"])

    @patch('gemini_client.call_gemini')
    def test_copilot_with_valid_data(self, mock_gemini):
        """TEST 8: Copilot with valid data should return grounded answer."""
        from fastapi.testclient import TestClient
        from main import app
        client = TestClient(app)
        
        mock_gemini.return_value = "Based on the data, the match rate is 85.5%."
        
        response = client.post("/ask", json={
            "question": "What is the match rate?",
            "context_data": {
                "summary": {"match_rate_percent": 85.5, "total_records": 100}
            }
        })
        data = response.json()
        self.assertEqual(data["status"], "success")
        self.assertIn("85.5", data["answer"])


if __name__ == '__main__':
    unittest.main()
