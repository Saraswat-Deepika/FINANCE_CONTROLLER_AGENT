from typing import List, Dict, Any, Tuple
from config import MATCHING_CONFIG
from evidence import build_evidence
from datetime import datetime, timedelta
from rapidfuzz import fuzz
from collections import defaultdict

def parse_date(d_str):
    if not d_str: return None
    try:
        return datetime.strptime(d_str, "%Y-%m-%d")
    except:
        return None

def dates_within_tolerance(d1_str, d2_str, tolerance):
    if not d1_str or not d2_str: return False
    try:
        d1 = datetime.strptime(d1_str, "%Y-%m-%d")
        d2 = datetime.strptime(d2_str, "%Y-%m-%d")
        return abs((d1 - d2).days) <= tolerance
    except:
        return False

def amounts_within_tolerance(a1, a2):
    if a1 is None or a2 is None: return False
    diff = abs(a1 - a2)
    max_a = max(abs(a1), abs(a2), 1)
    return diff <= MATCHING_CONFIG["amount_tolerance_absolute"] or (diff / max_a * 100) <= MATCHING_CONFIG["amount_tolerance_percentage"]

class MultiSourceMatcher:
    def __init__(self, bank_records, settle_records, ledger_records):
        self.bank = bank_records
        self.settle = settle_records
        self.ledger = ledger_records
        
        self.matched_bank = set()
        self.matched_settle = set()
        self.matched_ledger = set()
        
        self.groups = []
        self.group_counter = 1
        
        # Build O(1) Hash Indexes
        self.settle_by_utr = defaultdict(list)
        self.ledger_by_utr = defaultdict(list)
        self.settle_by_exact = defaultdict(list)
        self.ledger_by_exact = defaultdict(list)
        self.settle_by_date = defaultdict(list)
        self.ledger_by_date = defaultdict(list)
        
        # Populate Settlement Indexes
        for idx, rec in enumerate(self.settle):
            n = rec["normalized_record"]
            if n["utr"]:
                self.settle_by_utr[n["utr"]].append(idx)
            if n["amount"] is not None and n["date"]:
                self.settle_by_exact[(n["amount"], n["date"])].append(idx)
            if n["date"]:
                self.settle_by_date[n["date"]].append(idx)
                
        # Populate Ledger Indexes
        for idx, rec in enumerate(self.ledger):
            n = rec["normalized_record"]
            if n["utr"]:
                self.ledger_by_utr[n["utr"]].append(idx)
            if n["amount"] is not None and n["date"]:
                self.ledger_by_exact[(n["amount"], n["date"])].append(idx)
            if n["date"]:
                self.ledger_by_date[n["date"]].append(idx)
        
    def add_group(self, b_idx, s_idx, l_idx, status, method, score, factors=None):
        bank_rec = self.bank[b_idx] if b_idx is not None else None
        settle_rec = self.settle[s_idx] if s_idx is not None else None
        ledger_rec = self.ledger[l_idx] if l_idx is not None else None
        
        if b_idx is not None: self.matched_bank.add(b_idx)
        if s_idx is not None: self.matched_settle.add(s_idx)
        if l_idx is not None: self.matched_ledger.add(l_idx)
        
        ev_data = build_evidence(
            bank_rec["original_record"] if bank_rec else None,
            settle_rec["original_record"] if settle_rec else None,
            ledger_rec["original_record"] if ledger_rec else None,
            status, score, factors
        )
        
        ev_data["group_id"] = f"REC-{self.group_counter:04d}"
        ev_data["match_method"] = method
        ev_data["bank"] = bank_rec["original_record"] if bank_rec else None
        ev_data["settlement"] = settle_rec["original_record"] if settle_rec else None
        ev_data["ledger"] = ledger_rec["original_record"] if ledger_rec else None
        
        self.groups.append(ev_data)
        self.group_counter += 1
        
    def _find_first_unmatched(self, indices, matched_set, condition=lambda x: True, records=None):
        """Finds the first unmatched index in a list of candidates that satisfies the condition."""
        for idx in indices:
            if idx not in matched_set:
                if records is None or condition(records[idx]["normalized_record"]):
                    return idx
        return None

    def _get_date_window_indices(self, target_date_str, tolerance_days, index_map):
        """Returns all indices from index_map for dates within tolerance_days of target_date_str."""
        indices = []
        target_date = parse_date(target_date_str)
        if not target_date:
            return indices
            
        for d in range(-tolerance_days, tolerance_days + 1):
            check_date = target_date + timedelta(days=d)
            check_date_str = check_date.strftime("%Y-%m-%d")
            if check_date_str in index_map:
                indices.extend(index_map[check_date_str])
        return indices

    def run(self):
        # Stage 5: Duplicate Suspected in Bank
        bank_hashes = {}
        for b_idx, full_b in enumerate(self.bank):
            b = full_b["normalized_record"]
            h = f"{b['utr']}_{b['amount']}_{b['date']}"
            if h in bank_hashes:
                self.add_group(b_idx, None, None, "DUPLICATE_SUSPECTED", "DUPLICATE_DETECTED", 0.0)
                self.matched_bank.add(bank_hashes[h])
            else:
                bank_hashes[h] = b_idx

        # Stage 1: Exact ID
        for b_idx, full_b in enumerate(self.bank):
            if b_idx in self.matched_bank: continue
            b = full_b["normalized_record"]
            
            if b["utr"]:
                s_idx = self._find_first_unmatched(self.settle_by_utr.get(b["utr"], []), self.matched_settle)
                l_idx = self._find_first_unmatched(self.ledger_by_utr.get(b["utr"], []), self.matched_ledger)
                
                if s_idx is not None and l_idx is not None:
                    # Check if financials conflict heavily
                    s = self.settle[s_idx]["normalized_record"]
                    l = self.ledger[l_idx]["normalized_record"]
                    if b["amount"] != s["amount"] or b["amount"] != l["amount"]:
                        # Exists UTR but amount mismatch
                        if amounts_within_tolerance(b["amount"], s["amount"]):
                            self.add_group(b_idx, s_idx, l_idx, "FUZZY_MATCHED", "AMOUNT_TOLERANCE", 0.8)
                        else:
                            self.add_group(b_idx, s_idx, l_idx, "NEEDS_REVIEW", "EXACT_UTR", 0.5)
                    else:
                        self.add_group(b_idx, s_idx, l_idx, "FULLY_MATCHED", "EXACT_UTR", 1.0)
                    continue
                    
                # Partial Matches
                if s_idx is not None or l_idx is not None:
                    self.add_group(b_idx, s_idx, l_idx, "PARTIAL_MATCH", "EXACT_UTR", 0.7)
                    continue

        # Stage 2: Exact Financial (No UTR)
        for b_idx, full_b in enumerate(self.bank):
            if b_idx in self.matched_bank: continue
            b = full_b["normalized_record"]
            
            key = (b["amount"], b["date"])
            s_idx = self._find_first_unmatched(self.settle_by_exact.get(key, []), self.matched_settle)
            l_idx = self._find_first_unmatched(self.ledger_by_exact.get(key, []), self.matched_ledger)
            
            if s_idx is not None and l_idx is not None:
                self.add_group(b_idx, s_idx, l_idx, "FULLY_MATCHED", "EXACT_AMOUNT_DATE", 0.95)

        # Stage 3: Date Tolerance
        for b_idx, full_b in enumerate(self.bank):
            if b_idx in self.matched_bank: continue
            b = full_b["normalized_record"]
            
            s_candidates = self._get_date_window_indices(b["date"], MATCHING_CONFIG["date_tolerance_days"], self.settle_by_date)
            l_candidates = self._get_date_window_indices(b["date"], MATCHING_CONFIG["date_tolerance_days"], self.ledger_by_date)
            
            s_idx = self._find_first_unmatched(s_candidates, self.matched_settle, lambda s: s["amount"] == b["amount"], self.settle)
            l_idx = self._find_first_unmatched(l_candidates, self.matched_ledger, lambda l: l["amount"] == b["amount"], self.ledger)
            
            if s_idx is not None and l_idx is not None:
                self.add_group(b_idx, s_idx, l_idx, "FUZZY_MATCHED", "DATE_TOLERANCE", 0.85)

        # Stage 4: Amount Tolerance
        for b_idx, full_b in enumerate(self.bank):
            if b_idx in self.matched_bank: continue
            b = full_b["normalized_record"]
            
            s_candidates = self.settle_by_date.get(b["date"], [])
            l_candidates = self.ledger_by_date.get(b["date"], [])
            
            s_idx = self._find_first_unmatched(s_candidates, self.matched_settle, lambda s: amounts_within_tolerance(s["amount"], b["amount"]), self.settle)
            l_idx = self._find_first_unmatched(l_candidates, self.matched_ledger, lambda l: amounts_within_tolerance(l["amount"], b["amount"]), self.ledger)
            
            if s_idx is not None and l_idx is not None:
                self.add_group(b_idx, s_idx, l_idx, "FUZZY_MATCHED", "AMOUNT_TOLERANCE", 0.85)

        # Stage 5: Fuzzy Strings
        for b_idx, full_b in enumerate(self.bank):
            if b_idx in self.matched_bank: continue
            b = full_b["normalized_record"]
            
            best_s_idx, best_l_idx = None, None
            best_score = 0
            
            s_candidates = self._get_date_window_indices(b["date"], MATCHING_CONFIG["date_tolerance_days"], self.settle_by_date)
            
            for s_idx in s_candidates:
                if s_idx in self.matched_settle: continue
                s = self.settle[s_idx]["normalized_record"]
                if amounts_within_tolerance(s["amount"], b["amount"]):
                    merch_score = fuzz.token_set_ratio(b["narration"], s["merchant"])
                    if merch_score > best_score:
                        best_score = merch_score
                        best_s_idx = s_idx
                        
            if best_s_idx is not None and best_score >= MATCHING_CONFIG["fuzzy_threshold_merchant"]:
                l_candidates = self._get_date_window_indices(b["date"], MATCHING_CONFIG["date_tolerance_days"], self.ledger_by_date)
                l_idx = self._find_first_unmatched(l_candidates, self.matched_ledger, lambda l: amounts_within_tolerance(l["amount"], b["amount"]), self.ledger)
                self.add_group(b_idx, best_s_idx, l_idx, "FUZZY_MATCHED", "FUZZY_MERCHANT", 0.7 + (best_score/100)*0.3)

        # Stage 7: Unmatched
        for b_idx, full_b in enumerate(self.bank):
            if b_idx not in self.matched_bank:
                self.add_group(b_idx, None, None, "UNMATCHED", "NONE", 0.0)
                
        for s_idx, full_s in enumerate(self.settle):
            if s_idx not in self.matched_settle:
                self.add_group(None, s_idx, None, "UNMATCHED", "NONE", 0.0)
                
        for l_idx, full_l in enumerate(self.ledger):
            if l_idx not in self.matched_ledger:
                self.add_group(None, None, l_idx, "UNMATCHED", "NONE", 0.0)
                
        return self.groups
