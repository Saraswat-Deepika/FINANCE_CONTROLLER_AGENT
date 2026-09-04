import json
import time
from typing import TypedDict, List, Dict, Any, Optional
from langgraph.graph import StateGraph, END
from investigation_tools import InvestigationTools

try:
    from gemini_client import call_gemini, GeminiPermanentError
except ImportError:
    from engine.gemini_client import call_gemini, GeminiPermanentError

# 1. State Definition
class InvestigationState(TypedDict):
    exception_id: str
    transaction_id: str
    exception_type: str
    source_records: dict
    candidate_records: list
    evidence: list
    investigation_steps: list
    root_cause: Optional[str]
    resolution: Optional[str]
    confidence: float
    recommendation: Optional[str]
    priority: str
    age: int
    assigned_reviewer: Optional[str]
    notes: list
    iteration: int
    tool_requests: list
    tools_instance: InvestigationTools

# 2. Nodes
def classify_exception_node(state: InvestigationState):
    """Determine initial exception type based on source records if not already specific."""
    steps = state.get("investigation_steps", [])
    exc_type = state.get("exception_type", "UNKNOWN_EXCEPTION")
    
    bank = state["source_records"].get("bank")
    settle = state["source_records"].get("settlement")
    ledger = state["source_records"].get("ledger")
    
    # Simple rule-based classification based on the matcher's status
    if exc_type == "DUPLICATE_SUSPECTED":
        exc_type = "DUPLICATE_TRANSACTION"
    elif exc_type == "UNMATCHED":
        if bank and not settle:
            exc_type = "MISSING_SETTLEMENT"
        elif settle and not bank:
            exc_type = "MISSING_BANK_RECORD"
        elif ledger and not settle:
            exc_type = "MISSING_SETTLEMENT"
    elif exc_type in ["NEEDS_REVIEW", "PARTIAL_MATCH", "FUZZY_MATCHED"]:
        if bank and settle and bank.get("amount") != settle.get("amount"):
            exc_type = "AMOUNT_MISMATCH"
        elif bank and settle and bank.get("date") != settle.get("date"):
            exc_type = "SETTLEMENT_DELAY"
            
    steps.append(f"Classified exception as {exc_type}")
    
    return {
        "exception_type": exc_type,
        "investigation_steps": steps,
        "iteration": 0
    }

def llm_reasoning_node(state: InvestigationState):
    """Ask LLM what to do next (call a tool or resolve)."""
    iteration = state.get("iteration", 0)
    steps = state.get("investigation_steps", [])
    
    if iteration > 3:
        # Force resolution if it loops too much
        return {
            "root_cause": "Max iterations reached without clear evidence.",
            "resolution": "UNRESOLVED",
            "confidence": 0.0,
            "recommendation": "Manual review required due to complex or conflicting data."
        }
        
    prompt = f"""
    You are an AI Finance Controller investigating a reconciliation exception.
    
    Exception Type: {state['exception_type']}
    Transaction ID: {state['transaction_id']}
    
    Source Records:
    {json.dumps(state['source_records'], default=str)}
    
    Evidence Collected So Far:
    {json.dumps(state['evidence'], default=str)}
    
    You have access to the following deterministic tools:
    1. "calculate_amount_difference": {{"amount1": float, "amount2": float}}
    2. "calculate_date_difference": {{"date1_str": str, "date2_str": str}}
    3. "find_related_fees": {{"diff_amount": float}}
    4. "find_related_refunds": {{"diff_amount": float}}
    5. "find_related_taxes": {{"diff_amount": float}}
    6. "check_settlement_timing": {{"txn_date": str, "settle_date": str}}
    7. "find_transaction_by_utr": {{"source": "bank"|"settlement"|"ledger", "utr": str}}
    
    Instructions:
    - If you don't have enough evidence to explain the discrepancy, request a tool.
    - If you have requested tools and gathered evidence that fully explains the issue (e.g. fee matches difference exactly), issue a final decision.
    - DO NOT hallucinate financial facts. If the fee tool returns empty, you CANNOT conclude it's a fee.
    - For AMOUNT_MISMATCH, you must calculate the difference first, then look for fees/refunds/taxes matching that difference.
    
    Respond STRICTLY in JSON:
    {{
        "tool_calls": [ {{"name": "tool_name", "args": {{"arg1": "val1"}} }} ],
        "final_decision": {{
            "root_cause": "Detailed explanation of what went wrong based ONLY on evidence.",
            "resolution": "AI_RESOLVED" | "NEEDS_REVIEW" | "UNRESOLVED",
            "confidence": float (0.0 to 1.0),
            "recommendation": "What the user should do next."
        }}
    }}
    (Provide 'tool_calls' if you need more data, OR 'final_decision' if you are done. Not both.)
    """
    
    try:
        response = call_gemini(prompt, is_json=True, temperature=0.1)
        
        tool_calls = response.get("tool_calls", [])
        final_decision = response.get("final_decision")
        
        if final_decision:
            # Policy override
            conf = final_decision.get("confidence", 0.0)
            res = final_decision.get("resolution", "UNRESOLVED")
            
            if conf >= 0.90 and len(state.get("evidence", [])) > 0 and res != "UNRESOLVED":
                res = "AI_RESOLVED"
            elif conf >= 0.70 and res != "UNRESOLVED":
                res = "NEEDS_REVIEW"
            else:
                res = "UNRESOLVED"
                
            steps.append(f"AI concluded investigation with {res} ({int(conf*100)}% confidence)")
            return {
                "root_cause": final_decision.get("root_cause"),
                "resolution": res,
                "confidence": conf,
                "recommendation": final_decision.get("recommendation"),
                "investigation_steps": steps
            }
        else:
            steps.append(f"AI requested tools: {[t['name'] for t in tool_calls]}")
            return {
                "tool_requests": tool_calls,
                "investigation_steps": steps,
                "iteration": iteration + 1
            }
            
    except GeminiPermanentError as e:
        steps.append(f"AI configuration error: {str(e)}")
        return {
            "root_cause": "AI service configuration error. Deterministic reconciliation evidence is still available.",
            "resolution": "UNRESOLVED",
            "confidence": 0.0,
            "recommendation": "AI service needs configuration fix. Please review the exception manually using the available evidence.",
            "investigation_steps": steps
        }
    except Exception as e:
        steps.append(f"AI reasoning failed: {str(e)}")
        return {
            "root_cause": "AI explanation unavailable. Deterministic reconciliation evidence is still available.",
            "resolution": "UNRESOLVED",
            "confidence": 0.0,
            "recommendation": "AI service temporarily unavailable. Manual review required.",
            "investigation_steps": steps
        }

def execute_tools_node(state: InvestigationState):
    """Execute the tools requested by the LLM."""
    tool_requests = state.get("tool_requests", [])
    evidence = state.get("evidence", [])
    tools = state.get("tools_instance")
    
    for req in tool_requests:
        name = req.get("name")
        args = req.get("args", {})
        
        result = None
        try:
            if name == "calculate_amount_difference":
                result = tools.calculate_amount_difference(args.get("amount1"), args.get("amount2"))
            elif name == "calculate_date_difference":
                result = tools.calculate_date_difference(args.get("date1_str"), args.get("date2_str"))
            elif name == "find_related_fees":
                result = tools.find_related_fees(args.get("diff_amount"))
            elif name == "find_related_refunds":
                result = tools.find_related_refunds(args.get("diff_amount"))
            elif name == "find_related_taxes":
                result = tools.find_related_taxes(args.get("diff_amount"))
            elif name == "check_settlement_timing":
                result = tools.check_settlement_timing(args.get("txn_date"), args.get("settle_date"))
            elif name == "find_transaction_by_utr":
                result = tools.find_transaction_by_utr(args.get("source"), args.get("utr"))
                
            evidence.append({
                "tool": name,
                "args": args,
                "result": result
            })
        except Exception as e:
            evidence.append({
                "tool": name,
                "args": args,
                "error": str(e)
            })
            
    return {
        "evidence": evidence,
        "tool_requests": []
    }

def route_next_step(state: InvestigationState):
    """Determine whether to route back to tools or finish."""
    if state.get("resolution") is not None:
        return "end"
    if state.get("tool_requests"):
        return "execute_tools_node"
    return "end"

# 3. Build Graph
def build_investigation_graph():
    workflow = StateGraph(InvestigationState)
    
    workflow.add_node("classify_exception_node", classify_exception_node)
    workflow.add_node("llm_reasoning_node", llm_reasoning_node)
    workflow.add_node("execute_tools_node", execute_tools_node)
    
    workflow.set_entry_point("classify_exception_node")
    workflow.add_edge("classify_exception_node", "llm_reasoning_node")
    
    workflow.add_conditional_edges(
        "llm_reasoning_node",
        route_next_step,
        {
            "execute_tools_node": "execute_tools_node",
            "end": END
        }
    )
    
    workflow.add_edge("execute_tools_node", "llm_reasoning_node")
    
    return workflow.compile()

def calculate_priority(amount: float, exc_type: str, confidence: float) -> str:
    if amount and amount >= 10000: return "CRITICAL"
    if exc_type in ["MISSING_SETTLEMENT", "DUPLICATE_TRANSACTION"]: return "HIGH"
    if confidence < 0.50: return "HIGH"
    if amount and amount >= 1000: return "MEDIUM"
    return "LOW"

def run_investigation(exception_group: dict, tools: InvestigationTools) -> dict:
    """Wrapper to run the investigation for a single exception group."""
    graph = build_investigation_graph()
    
    bank = exception_group.get("bank", {})
    settle = exception_group.get("settlement", {})
    ledger = exception_group.get("ledger", {})
    
    # Try to extract a stable transaction ID and amount for reporting
    txn_id = "UNKNOWN"
    amt = 0.0
    for src in [bank, settle, ledger]:
        if src:
            if src.get("id"): txn_id = src["id"]
            if src.get("amount") is not None: amt = float(src["amount"])
            break
            
    candidate_records = []
    # If ambiguous, populate candidates
    if exception_group.get("status") in ["DUPLICATE_SUSPECTED", "PARTIAL_MATCH", "UNMATCHED"]:
        # Find candidates by amount
        if amt > 0:
            cands1 = tools.find_records_by_amount("bank", amt, tolerance=10)
            cands2 = tools.find_records_by_amount("settlement", amt, tolerance=10)
            cands3 = tools.find_records_by_amount("ledger", amt, tolerance=10)
            candidate_records.extend(cands1 + cands2 + cands3)
            
    # Remove duplicates from candidates by id
    seen_ids = set()
    unique_candidates = []
    for c in candidate_records:
        cid = c.get("normalized_record", {}).get("id")
        if cid and cid not in seen_ids:
            seen_ids.add(cid)
            unique_candidates.append(c)
            
    initial_state = {
        "exception_id": exception_group.get("group_id", f"EXC-{int(time.time()*1000)}"),
        "transaction_id": txn_id,
        "exception_type": exception_group.get("status", "UNKNOWN_EXCEPTION"),
        "source_records": {
            "bank": bank,
            "settlement": settle,
            "ledger": ledger
        },
        "candidate_records": unique_candidates,
        "evidence": [],
        "investigation_steps": [f"Exception detected: {exception_group.get('status')}"],
        "root_cause": None,
        "resolution": None,
        "confidence": 0.0,
        "recommendation": None,
        "priority": "LOW", # Computed after graph or here
        "age": 0, # Hackathon default
        "assigned_reviewer": None,
        "notes": [],
        "iteration": 0,
        "tool_requests": [],
        "tools_instance": tools
    }
    
    final_state = graph.invoke(initial_state)
    
    # Compute priority based on finalized state
    final_state["priority"] = calculate_priority(amt, final_state.get("exception_type", ""), final_state.get("confidence", 0.0))
    
    # Clean up non-serializable objects before returning
    if "tools_instance" in final_state:
        del final_state["tools_instance"]
        
    return final_state
