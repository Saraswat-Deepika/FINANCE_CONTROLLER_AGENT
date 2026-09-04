import re
from datetime import datetime
from rapidfuzz import fuzz

class Normalizer:
    @staticmethod
    def normalize_string(val):
        if pd.isna(val) if 'pd' in globals() else not val or str(val).lower() in ["nan", "null", "none"]:
            return ""
        # Lowercase, strip, remove dashes/underscores and extra spaces
        s = str(val).lower()
        s = re.sub(r'[-_]', ' ', s)
        s = re.sub(r'\s+', ' ', s).strip()
        return s
        
    @staticmethod
    def normalize_id(val):
        if pd.isna(val) if 'pd' in globals() else not val or str(val).lower() in ["nan", "null", "none"]:
            return ""
        # Remove all whitespace and special chars, uppercase
        s = str(val).upper()
        s = re.sub(r'[^A-Z0-9]', '', s)
        return s
        
    @staticmethod
    def normalize_amount(val):
        try:
            return round(float(val), 2)
        except:
            return 0.0
            
    @staticmethod
    def normalize_date(val):
        if pd.isna(val) if 'pd' in globals() else not val or str(val).lower() in ["nan", "null", "none"]:
            return None
            
        s = str(val).strip()
        formats = [
            "%Y-%m-%d", "%d-%m-%Y", "%Y/%m/%d", "%d/%m/%Y"
        ]
        
        for fmt in formats:
            try:
                dt = datetime.strptime(s, fmt)
                return dt.strftime("%Y-%m-%d") # Standardize to ISO
            except ValueError:
                pass
        return None
        
def apply_normalization(df_bank, df_settle, df_ledger):
    import pandas as pd
    # Bank Normalization
    bank_records = []
    for _, row in df_bank.iterrows():
        # Handle original record nan for json
        orig = row.where(pd.notnull(row), None).to_dict()
        bank_records.append({
            "source": "bank",
            "original_record": orig,
            "normalized_record": {
                "id": Normalizer.normalize_string(row.get("transaction_id") or row.get("id") or row.get("reference")),
                "amount": Normalizer.normalize_amount(row.get("amount") or row.get("txn_amount")),
                "date": Normalizer.normalize_date(row.get("date") or row.get("transaction_date")),
                "utr": Normalizer.normalize_id(row.get("utr") or row.get("reference_number")),
                "narration": Normalizer.normalize_string(row.get("narration")),
            }
        })
        
    # Settlement Normalization
    settle_records = []
    for _, row in df_settle.iterrows():
        orig = row.where(pd.notnull(row), None).to_dict()
        settle_records.append({
            "source": "settlement",
            "original_record": orig,
            "normalized_record": {
                "id": Normalizer.normalize_string(row.get("settlement_id") or row.get("id")),
                "amount": Normalizer.normalize_amount(row.get("amount") or row.get("gross_amount")),
                "date": Normalizer.normalize_date(row.get("settlement_date") or row.get("date")),
                "utr": Normalizer.normalize_id(row.get("utr")),
                "merchant": Normalizer.normalize_string(row.get("merchant")),
            }
        })
        
    # Ledger Normalization
    ledger_records = []
    for _, row in df_ledger.iterrows():
        orig = row.where(pd.notnull(row), None).to_dict()
        ledger_records.append({
            "source": "ledger",
            "original_record": orig,
            "normalized_record": {
                "id": Normalizer.normalize_string(row.get("ledger_id") or row.get("id")),
                "amount": Normalizer.normalize_amount(row.get("amount")),
                "date": Normalizer.normalize_date(row.get("transaction_date") or row.get("date")),
                "utr": Normalizer.normalize_id(row.get("utr")),
                "customer": Normalizer.normalize_string(row.get("customer")),
            }
        })
        
    return bank_records, settle_records, ledger_records
