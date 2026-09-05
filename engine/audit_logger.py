import json
from datetime import datetime
import os
import uuid
import requests

AUDIT_LOG_FILE = "audit_log.jsonl"
EXPRESS_API_URL = os.environ.get("EXPRESS_SERVER_URL", "http://localhost:5000/api/audit/event")

import concurrent.futures
_audit_executor = concurrent.futures.ThreadPoolExecutor(max_workers=10)

def _send_log(url, entry):
    try:
        requests.post(url, json=entry, timeout=5)
    except Exception as e:
        pass # Silently fail to avoid console spam in large loops

def log_audit_event(event_type: str, actor_type: str, details: dict):
    """Log an event to the Express MongoDB audit collection (and optionally local file)."""
    
    # Ensure event_id is generated if not provided
    event_id = details.get("event_id") or str(uuid.uuid4())
    details["event_id"] = event_id
    
    log_entry = {
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "event_type": event_type,
        "actor_type": actor_type,
        **details
    }
    
    # Fallback log to file
    try:
        with open(AUDIT_LOG_FILE, "a") as f:
            f.write(json.dumps(log_entry) + "\n")
    except Exception as e:
        pass
        
    # Send to Express Server (Asynchronous)
    _audit_executor.submit(_send_log, EXPRESS_API_URL, log_entry)
        
    return event_id

def log_system_event(event_type: str, run_id: str, details: dict = None):
    """Log system-level lifecycle events."""
    return log_audit_event(
        event_type=event_type,
        actor_type="SYSTEM",
        details={
            "run_id": run_id,
            "metadata": details or {}
        }
    )

def log_ai_decision(investigation_state: dict):
    """Log an AI investigation result."""
    return log_audit_event(
        event_type="AI_RESOLUTION_PROPOSED",
        actor_type="AI",
        details={
            "exception_id": investigation_state.get("exception_id", investigation_state.get("group_id")),
            "transaction_id": investigation_state.get("transaction_id"),
            "run_id": investigation_state.get("run_id"),
            "decision": investigation_state.get("resolution"),
            "reason": investigation_state.get("root_cause"),
            "metadata": {
                "confidence": investigation_state.get("confidence"),
                "investigation_steps": investigation_state.get("investigation_steps", [])
            }
        }
    )

def log_human_action(exception_id: str, transaction_id: str, action: str, previous_status: str, final_status: str, reason: str = None, actor_id: str = "Unknown", actor_role: str = "REVIEWER", notes: str = None, ai_decision: str = None, run_id: str = None):
    """Log a human action (Accept, Reject, Review, Override)."""
    
    event_id = str(uuid.uuid4())
    
    details = {
        "event_id": event_id,
        "exception_id": exception_id,
        "transaction_id": transaction_id,
        "run_id": run_id,
        "previous_status": previous_status,
        "new_status": final_status,
        "final_status": final_status, # backward compatibility
        "human_action": action,
        "action": action, # backward compatibility
        "human_decision": final_status,
        "AI_decision": ai_decision or previous_status,
        "human_reason": reason,
        "reason": reason,
        "actor_id": actor_id,
        "actor_role": actor_role,
        "actor_name": actor_id
    }
    
    if notes:
        details["notes"] = notes
        
    log_audit_event(
        event_type=f"HUMAN_{action.upper().replace(' ', '_')}",
        actor_type="HUMAN",
        details=details
    )
    return event_id
