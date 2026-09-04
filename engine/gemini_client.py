"""
Centralized Gemini AI Service for Finance Controller.

Single source of truth for all Gemini API interactions.
All other modules (investigation_graph, reasoning, reasoning_graph, main.py /ask)
import `call_gemini` from this module.

Configuration:
    GEMINI_API_KEY  — required, set in engine/.env
    GEMINI_MODEL    — optional, defaults to gemini-3.6-flash
"""

import os
import re
import time
import json
from dotenv import load_dotenv
from google import genai
from google.genai import types
import threading

load_dotenv(override=True)

# ---------------------------------------------------------------------------
# Configuration — single source of truth
# ---------------------------------------------------------------------------
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.6-flash")
MAX_RETRIES = 3

# Initialize client once at module load
_client = None
if GEMINI_API_KEY and GEMINI_API_KEY != "your_gemini_api_key_here":
    _client = genai.Client(api_key=GEMINI_API_KEY)
    print(f"[Gemini Service] Initialized — Model: {GEMINI_MODEL}")
else:
    print("[Gemini Service] WARNING: GEMINI_API_KEY not set. AI features will be unavailable.")

# Global timestamp for inter-request rate limiting
_last_call_time = 0
_MIN_REQUEST_INTERVAL = 4.5  # seconds between requests (15 RPM safe)
_rate_limit_lock = threading.Lock()


# ---------------------------------------------------------------------------
# Error classification
# ---------------------------------------------------------------------------
class GeminiPermanentError(Exception):
    """Non-retryable error (404 model not found, 401 bad key, 400 bad request)."""
    pass


class GeminiRetryableError(Exception):
    """Retryable error (429 rate limit, 5xx server error, network timeout)."""
    def __init__(self, message, suggested_delay=None):
        super().__init__(message)
        self.suggested_delay = suggested_delay


def _classify_error(error):
    """
    Classify a Gemini API error as permanent or retryable.
    
    Returns:
        GeminiPermanentError or GeminiRetryableError
    """
    error_str = str(error)
    
    # --- Permanent errors: DO NOT RETRY ---
    
    # 404 — Model not found
    if "404" in error_str and ("NOT_FOUND" in error_str or "not found" in error_str.lower()):
        return GeminiPermanentError(
            f"[CONFIG ERROR] Model '{GEMINI_MODEL}' not found. "
            f"Update GEMINI_MODEL in engine/.env. API said: {error_str[:200]}"
        )
    
    # 401 / 403 — Authentication/authorization failure
    if any(code in error_str for code in ["401", "403", "UNAUTHENTICATED", "PERMISSION_DENIED"]):
        return GeminiPermanentError(
            f"[CONFIG ERROR] Invalid or unauthorized API key. "
            f"Check GEMINI_API_KEY in engine/.env. Error: {error_str[:200]}"
        )
    
    # 400 — Bad request (malformed prompt, invalid params)
    if "400" in error_str and ("INVALID" in error_str or "BAD_REQUEST" in error_str):
        return GeminiPermanentError(
            f"[REQUEST ERROR] Invalid request to Gemini API: {error_str[:200]}"
        )
    
    # --- Retryable errors: RETRY with backoff ---
    
    # 429 — Rate limit / quota exhausted
    if "429" in error_str or "RESOURCE_EXHAUSTED" in error_str:
        # Try to extract suggested retry delay from the API response
        suggested_delay = _extract_retry_delay(error_str)
        return GeminiRetryableError(
            f"[RATE LIMIT] Quota exceeded. Will retry after backoff.",
            suggested_delay=suggested_delay
        )
    
    # 5xx — Server errors
    if any(code in error_str for code in ["500", "502", "503", "INTERNAL", "UNAVAILABLE"]):
        return GeminiRetryableError(f"[SERVER ERROR] Gemini server error: {error_str[:200]}")
    
    # Network / timeout errors
    if any(keyword in error_str.lower() for keyword in ["timeout", "connection", "network", "refused"]):
        return GeminiRetryableError(f"[NETWORK ERROR] Connection issue: {error_str[:200]}")
    
    # Unknown errors — treat as retryable (conservative)
    return GeminiRetryableError(f"[UNKNOWN ERROR] {error_str[:200]}")


def _extract_retry_delay(error_str):
    """Extract the suggested retry delay from a 429 error response."""
    # Match patterns like: retryDelay': '29s'  or  "retryDelay": "4s"
    match = re.search(r"retryDelay['\"]?\s*[:=]\s*['\"]?(\d+)", error_str)
    if match:
        return int(match.group(1))
    # Match patterns like: Please retry in 29.331159291s
    match = re.search(r"retry in (\d+(?:\.\d+)?)s", error_str, re.IGNORECASE)
    if match:
        return int(float(match.group(1))) + 1  # Round up
    return None


# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------
def check_gemini_health():
    """
    Check if the Gemini service is properly configured and reachable.
    Returns a dict with status info — never raises.
    """
    if not _client:
        return {
            "status": "unavailable",
            "model": GEMINI_MODEL,
            "error": "GEMINI_API_KEY not configured"
        }
    
    try:
        response = _client.models.generate_content(
            model=GEMINI_MODEL,
            contents="Respond with exactly: OK",
            config=types.GenerateContentConfig(temperature=0.0)
        )
        return {
            "status": "ok",
            "model": GEMINI_MODEL,
            "message": "Gemini is reachable and responding"
        }
    except Exception as e:
        classified = _classify_error(e)
        return {
            "status": "error",
            "model": GEMINI_MODEL,
            "error": str(classified),
            "retryable": isinstance(classified, GeminiRetryableError)
        }


# ---------------------------------------------------------------------------
# Core API call with error classification and bounded retry
# ---------------------------------------------------------------------------
def call_gemini(prompt, is_json=False, temperature=0.2):
    """
    Send a prompt to Gemini and return the response.
    
    Args:
        prompt: The text prompt to send
        is_json: If True, request JSON response and parse it
        temperature: LLM temperature (0.0-1.0)
    
    Returns:
        Parsed JSON (dict/list) if is_json=True, else string
    
    Raises:
        GeminiPermanentError: For non-retryable config/request errors
        Exception: If all retries exhausted for retryable errors
    """
    global _last_call_time
    
    if not _client:
        raise GeminiPermanentError(
            "[CONFIG ERROR] Gemini API key missing or invalid. "
            "Set GEMINI_API_KEY in engine/.env"
        )
    
    # Configure response format
    mime_type = "application/json" if is_json else "text/plain"
    gen_config = types.GenerateContentConfig(
        response_mime_type=mime_type,
        temperature=temperature
    )
    
    last_error = None
    
    for attempt in range(MAX_RETRIES):
        # Inter-request rate limiting (must be inside loop for retries)
        with _rate_limit_lock:
            current_time = time.time()
            time_since_last = current_time - _last_call_time
            if time_since_last < _MIN_REQUEST_INTERVAL:
                sleep_time = _MIN_REQUEST_INTERVAL - time_since_last
                print(f"[Gemini Service] Rate limit throttle: waiting {sleep_time:.1f}s...")
                time.sleep(sleep_time)
            _last_call_time = time.time()
        try:
            print(f"[Gemini Service] Request {attempt + 1}/{MAX_RETRIES} | Model: {GEMINI_MODEL}")
            
            response = _client.models.generate_content(
                model=GEMINI_MODEL,
                contents=prompt,
                config=gen_config
            )
            
            content = response.text.strip()
            
            # Parse JSON response if requested
            if is_json:
                parsed = _parse_json_response(content)
                print(f"[Gemini Service] SUCCESS (JSON parsed)")
                return parsed
            else:
                print(f"[Gemini Service] SUCCESS (text returned)")
                return content
                
        except (GeminiPermanentError,):
            raise  # Already classified, don't retry
            
        except Exception as e:
            classified = _classify_error(e)
            
            # Permanent errors — fail immediately
            if isinstance(classified, GeminiPermanentError):
                print(f"[Gemini Service] PERMANENT ERROR: {classified}")
                raise classified
            
            # Retryable errors — backoff and retry
            last_error = classified
            if attempt < MAX_RETRIES - 1:
                # Calculate backoff: use API-suggested delay if available, else exponential
                if classified.suggested_delay and classified.suggested_delay > 5:
                    print(f"[Gemini Service] Quota exhausted (wait >5s). Failing fast to avoid hangs.")
                    raise classified
                elif classified.suggested_delay and classified.suggested_delay > 0:
                    backoff = min(classified.suggested_delay + 2, 90)  # Cap at 90s
                else:
                    backoff = min(2 * (2 ** attempt), 90)  # 2s, 4s, 8s (capped at 90s)
                
                print(f"[Gemini Service] RETRYABLE ERROR: {classified}")
                print(f"[Gemini Service] Retrying in {backoff}s (attempt {attempt + 2}/{MAX_RETRIES})...")
                time.sleep(backoff)
            else:
                print(f"[Gemini Service] EXHAUSTED all {MAX_RETRIES} retries. Last error: {classified}")
    
    # All retries exhausted
    raise last_error or Exception("Gemini request failed after all retries")


# ---------------------------------------------------------------------------
# JSON response parsing
# ---------------------------------------------------------------------------
def _parse_json_response(content):
    """
    Parse JSON from Gemini response text.
    Handles markdown code fences and extracts JSON objects/arrays.
    
    Returns:
        Parsed dict or list
    
    Raises:
        ValueError: If content cannot be parsed as valid JSON
    """
    # Strip markdown code fences
    cleaned = content.replace("```json", "").replace("```", "").strip()
    
    # Try direct parse first
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass
    
    # Try to extract JSON array
    arr_start = cleaned.find('[')
    arr_end = cleaned.rfind(']')
    if arr_start != -1 and arr_end != -1 and arr_end > arr_start:
        try:
            return json.loads(cleaned[arr_start:arr_end + 1])
        except json.JSONDecodeError:
            pass
    
    # Try to extract JSON object
    obj_start = cleaned.find('{')
    obj_end = cleaned.rfind('}')
    if obj_start != -1 and obj_end != -1 and obj_end > obj_start:
        try:
            return json.loads(cleaned[obj_start:obj_end + 1])
        except json.JSONDecodeError:
            pass
    
    raise ValueError(f"Could not parse Gemini response as JSON. Raw content: {content[:500]}")
