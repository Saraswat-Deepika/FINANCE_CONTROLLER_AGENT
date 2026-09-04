import json
from typing import TypedDict, List
from pydantic import BaseModel, ValidationError
from langgraph.graph import StateGraph, END

try:
    from gemini_client import call_gemini, GeminiPermanentError
except ImportError:
    from engine.gemini_client import call_gemini, GeminiPermanentError

# 1. Pydantic Schemas
class ReasoningItem(BaseModel):
    record_id: str
    reason: str

class ReasoningBatch(BaseModel):
    items: List[ReasoningItem]

# 2. LangGraph State definition
class ReconciliationState(TypedDict):
    matched_records: list       # already exact-matched, no LLM needed
    ambiguous_records: list     # fuzzy/needs_review/unmatched - needs LLM
    reasoned_records: list      # output after LLM reasoning
    retry_count: int
    validation_passed: bool

# 3. Nodes
def deterministic_node(state: ReconciliationState):
    matched = state.get("matched_records", [])
    print(f"[LangGraph] Entering deterministic_node — {len(matched)} records")
    
    reasoned = state.get("reasoned_records", [])
    # We assign a deterministic reason to fully matched
    for i, rec in enumerate(matched):
        reasoned.append({
            "record_id": f"matched_{i}",
            "reason": "Exact Match"
        })
    return {"reasoned_records": reasoned}

def gemini_reasoning_node(state: ReconciliationState):
    ambiguous = state.get("ambiguous_records", [])
    print(f"[LangGraph] Entering gemini_reasoning_node — {len(ambiguous)} records")
    
    if not ambiguous:
        return {"validation_passed": True}
        
    all_items = []
    validation_passed = True
    
    batch_size = 15
    batches = [ambiguous[i:i + batch_size] for i in range(0, len(ambiguous), batch_size)]
    
    for idx, batch in enumerate(batches):
        print(f"[LangGraph] Processing batch {idx+1}/{len(batches)}...")
        
        prompt = f"""
        Neeche {len(batch)} financial reconciliation records hain (JSON array).
        Har record mein 'evidence' aur 'status' diya gaya hai.
        Tumhara kaam hai is evidence ke base par ek short, concise, aur specific human-readable explanation (max 15 words) generate karna ki ye status kyun assign hua hai.
        
        Strict Rules:
        - Sirf diye gaye evidence data ko use karo.
        - Koi bhi factual value (amounts, dates, transaction IDs, fee amounts, missing sources) invent/hallucinate mat karo. Agar evidence missing hai to bolo: "Insufficient evidence for an automated conclusion."
        - Agar Unmatched hai, to strictly bolo ki kya missing hai based on 'missing_sources'.
        - Agar fee difference hai to gateway fee difference ka reason do.
        - Agar date difference hai to settlement delay explain karo.
        
        Response strictly in this JSON format:
        {{
            "items": [
                {{"record_id": "...", "reason": "..."}}
            ]
        }}
        
        Input Data (with evidence):
        {json.dumps(batch, default=str)}
        """
        
        try:
            response = call_gemini(prompt, is_json=True, temperature=0.1)
            if isinstance(response, list):
                response = {"items": response}
            # Validate with Pydantic
            validated_batch = ReasoningBatch(**response)
            all_items.extend([item.model_dump() for item in validated_batch.items])
        except Exception as e:
            print(f"[LangGraph] Validation failed for batch {idx+1}: {e}")
            validation_passed = False
            break # Break out to retry the whole process

    # Keep existing reasoned records, just append new ones if validation passed
    reasoned = [r for r in state.get("reasoned_records", []) if not r["record_id"].startswith("fuzzy_") and not r["record_id"].startswith("unmatched_")]
    
    if validation_passed:
        reasoned.extend(all_items)
        
    return {
        "reasoned_records": reasoned,
        "validation_passed": validation_passed
    }

def validation_node(state: ReconciliationState):
    passed = state.get("validation_passed", False)
    retry_count = state.get("retry_count", 0)
    
    if passed:
        print("[LangGraph] Validation passed")
        return {} # State stays same
    else:
        new_retry = retry_count + 1
        print(f"[LangGraph] Validation failed, retrying... (Attempt {new_retry})")
        return {"retry_count": new_retry}

def fallback_node(state: ReconciliationState):
    print("[LangGraph] Entering fallback_node — Exhausted retries")
    ambiguous = state.get("ambiguous_records", [])
    reasoned = state.get("reasoned_records", [])
    
    # Check which ones are missing and add fallback
    existing_ids = {r["record_id"] for r in reasoned}
    for rec in ambiguous:
        rec_id = rec.get("graph_id")
        if rec_id and rec_id not in existing_ids:
            reasoned.append({
                "record_id": rec_id,
                "reason": "Record missing from other sources — requires manual review (Fallback)"
            })
            
    return {"reasoned_records": reasoned}

# 4. Conditional logic
def should_continue(state: ReconciliationState):
    passed = state.get("validation_passed", False)
    retries = state.get("retry_count", 0)
    
    if passed:
        return "end"
    elif retries < 2:
        return "retry"
    else:
        return "fallback"

def has_ambiguous(state: ReconciliationState):
    if state.get("ambiguous_records", []):
        return "gemini_reasoning_node"
    return "end"

# 5. Graph compilation
def build_reconciliation_graph():
    workflow = StateGraph(ReconciliationState)
    
    workflow.add_node("deterministic_node", deterministic_node)
    workflow.add_node("gemini_reasoning_node", gemini_reasoning_node)
    workflow.add_node("validation_node", validation_node)
    workflow.add_node("fallback_node", fallback_node)
    
    workflow.set_entry_point("deterministic_node")
    
    workflow.add_conditional_edges(
        "deterministic_node",
        has_ambiguous,
        {
            "gemini_reasoning_node": "gemini_reasoning_node",
            "end": END
        }
    )
    
    workflow.add_edge("gemini_reasoning_node", "validation_node")
    
    workflow.add_conditional_edges(
        "validation_node",
        should_continue,
        {
            "retry": "gemini_reasoning_node",
            "fallback": "fallback_node",
            "end": END
        }
    )
    
    workflow.add_edge("fallback_node", END)
    
    return workflow.compile()

def run_reconciliation_graph(matched: list, ambiguous: list):
    graph = build_reconciliation_graph()
    
    initial_state = {
        "matched_records": matched,
        "ambiguous_records": ambiguous,
        "reasoned_records": [],
        "retry_count": 0,
        "validation_passed": False
    }
    
    final_state = graph.invoke(initial_state)
    return final_state
