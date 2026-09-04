from typing import List, Dict, Any
from datetime import datetime

class InvestigationTools:
    def __init__(self, bank_records: List[Dict], settle_records: List[Dict], ledger_records: List[Dict]):
        # Store records by source for querying
        self.datasets = {
            "bank": bank_records,
            "settlement": settle_records,
            "ledger": ledger_records
        }
        
    def _parse_date(self, d_str):
        if not d_str: return None
        try:
            return datetime.strptime(d_str, "%Y-%m-%d")
        except:
            return None

    def find_transaction_by_id(self, source: str, txn_id: str) -> List[Dict]:
        """Search exact transaction ID in a source."""
        if source not in self.datasets or not txn_id:
            return []
        res = []
        for r in self.datasets[source]:
            if r["normalized_record"]["id"] == txn_id:
                res.append(r)
        return res

    def find_transaction_by_utr(self, source: str, utr: str) -> List[Dict]:
        """Search exact UTR in a source."""
        if source not in self.datasets or not utr:
            return []
        res = []
        for r in self.datasets[source]:
            if r["normalized_record"]["utr"] == utr:
                res.append(r)
        return res

    def find_records_by_amount(self, source: str, amount: float, tolerance: float = 0.0) -> List[Dict]:
        """Search records by amount within a given tolerance."""
        if source not in self.datasets or amount is None:
            return []
        res = []
        for r in self.datasets[source]:
            r_amt = r["normalized_record"]["amount"]
            if r_amt is not None and abs(r_amt - amount) <= tolerance:
                res.append(r)
        return res

    def calculate_amount_difference(self, amount1: float, amount2: float) -> float:
        if amount1 is None or amount2 is None:
            return None
        return round(abs(amount1 - amount2), 2)

    def calculate_date_difference(self, date1_str: str, date2_str: str) -> int:
        d1 = self._parse_date(date1_str)
        d2 = self._parse_date(date2_str)
        if d1 and d2:
            return abs((d1 - d2).days)
        return None

    def check_settlement_timing(self, txn_date: str, settle_date: str, max_days: int = 3) -> Dict:
        """Check if settlement delay is within tolerance."""
        diff = self.calculate_date_difference(txn_date, settle_date)
        if diff is None:
            return {"status": "UNKNOWN", "days": None}
        if diff <= max_days:
            return {"status": "WITHIN_TOLERANCE", "days": diff}
        return {"status": "DELAYED", "days": diff}

    def find_related_fees(self, diff_amount: float, utr: str = None) -> List[Dict]:
        """Look for fee records matching the difference amount in the settlement or ledger."""
        fees = []
        for r in self.datasets["settlement"]:
            orig = r.get("original_record", {})
            
            # Check if there's an explicit fee column in original record
            fee_val = orig.get("fee") or orig.get("fees") or 0.0
            tax_val = orig.get("tax") or 0.0
            total_fee = float(fee_val) + float(tax_val)
            
            if total_fee > 0 and abs(total_fee - diff_amount) < 0.01:
                fees.append(r)
                continue
                
            # Fallback to separate record check
            amt = r["normalized_record"]["amount"]
            if amt and abs(amt - diff_amount) < 0.01:
                merch = r["normalized_record"].get("merchant", "").lower()
                if "fee" in merch or "charge" in merch:
                    fees.append(r)
        return fees

    def find_related_refunds(self, diff_amount: float, utr: str = None) -> List[Dict]:
        """Look for refund records matching the difference."""
        refunds = []
        for r in self.datasets["settlement"]:
            amt = r["normalized_record"]["amount"]
            if amt and abs(amt - diff_amount) < 0.01:
                merch = r["normalized_record"].get("merchant", "").lower()
                if "refund" in merch or "rev" in merch:
                    refunds.append(r)
        return refunds

    def find_related_taxes(self, diff_amount: float, utr: str = None) -> List[Dict]:
        """Look for tax records matching the difference."""
        taxes = []
        for r in self.datasets["settlement"]:
            amt = r["normalized_record"]["amount"]
            if amt and abs(amt - diff_amount) < 0.01:
                merch = r["normalized_record"].get("merchant", "").lower()
                if "tax" in merch or "gst" in merch:
                    taxes.append(r)
        return taxes

    def find_duplicate_candidates(self, source: str, utr: str, amount: float, date: str) -> List[Dict]:
        """Find records that match UTR, Amount, and Date in the same source."""
        if source not in self.datasets or not utr or amount is None:
            return []
        res = []
        for r in self.datasets[source]:
            nr = r["normalized_record"]
            if nr["utr"] == utr and nr["amount"] == amount and nr["date"] == date:
                res.append(r)
        return res
