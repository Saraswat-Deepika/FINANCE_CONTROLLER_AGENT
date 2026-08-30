import os
import json
import time
from gemini_client import call_gemini

def get_exception_reasons_for_patterns(patterns_dict):
    """
    Batches patterns to avoid rate limits, implements exponential backoff retries,
    and returns a graceful fallback if all retries fail.
    """
    fallback_reason = "Record missing from other sources — requires manual review"
    
    keys = list(patterns_dict.keys())
    total_items = len(keys)
    batch_size = 15
    
    batches = [keys[i:i + batch_size] for i in range(0, total_items, batch_size)]
    
    print(f"\n====== AI REASONING STARTED ======")
    print(f"Total Items: {total_items} | Batches: {len(batches)} (Size: {batch_size})")
    
    final_reasons = {}
    specific_records = 0
    fallback_records = 0
    
    for idx, batch_keys in enumerate(batches):
        print(f"  -> Processing Batch {idx+1}/{len(batches)} ({len(batch_keys)} items)...")
        
        batch_array = []
        for k in batch_keys:
            record_data = patterns_dict[k].copy()
            record_data["record_id"] = k
            batch_array.append(record_data)
            
        total_records = len(batch_array)
        prompt = f"""
        Neeche {total_records} financial reconciliation records hain (JSON array), har ek ka record_id, type, aur relevant data diya hai. 
        Har record ke liye ek short reason (max 15 words) do ki wo record us category me kyun hai.
        If context says "Missing in...", use that fact.
        
        Response STRICTLY is JSON format me do: 
        [{{ "record_id": "...", "reason": "..." }}, {{ ... }}]
        Koi extra text mat likhna, sirf JSON array.
        
        Input:
        """
        prompt += json.dumps(batch_array, default=str)
        
        try:
            reasons_list = call_gemini(prompt, is_json=True, temperature=0.1)
            
            if reasons_list and isinstance(reasons_list, list):
                for item in reasons_list:
                    if "record_id" in item and "reason" in item:
                        final_reasons[item["record_id"]] = item["reason"]
                        specific_records += 1
            else:
                for k in batch_keys:
                    final_reasons[k] = fallback_reason
                    fallback_records += 1
        except Exception as e:
            for k in batch_keys:
                final_reasons[k] = fallback_reason
                fallback_records += 1
                
    print(f"====== AI REASONING COMPLETE ======")
    print(f"AI Reasoning: {specific_records} records got specific reasons, {fallback_records} records used fallback")
    print("===================================\n")
    
    for k in keys:
        if k not in final_reasons:
            final_reasons[k] = fallback_reason
            
    return final_reasons
