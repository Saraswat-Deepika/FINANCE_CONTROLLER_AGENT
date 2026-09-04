import pandas as pd
import numpy as np

def _check_missing(row, possible_cols):
    for c in possible_cols:
        if c in row.index and pd.notnull(row[c]) and str(row[c]).strip() != "":
            return False, row[c]
    return True, None

def validate_dataframe(df: pd.DataFrame, source_type: str) -> dict:
    """
    Validates a dataframe against source-specific schemas and returns detailed quality metrics.
    """
    total_records = len(df)
    
    if total_records == 0:
        return {
            "records": 0,
            "valid_records": 0,
            "invalid_records": 0,
            "duplicates": 0,
            "errors": [{
                "source": source_type,
                "row": "-",
                "field": "-",
                "value": "-",
                "error": "File is empty"
            }],
            "preview": []
        }
        
    errors = []
    valid = 0
    invalid = 0
    
    # Identify schema expectations
    if source_type == "bank":
        id_cols = ["transaction_id", "id", "reference"]
        date_cols = ["date", "transaction_date"]
        amount_cols = ["amount", "txn_amount"]
        utr_cols = ["utr", "reference_number"]
    elif source_type == "settlement":
        id_cols = ["settlement_id", "id"]
        date_cols = ["settlement_date", "date"]
        amount_cols = ["amount", "gross_amount", "net_amount"]
        utr_cols = ["utr"]
    else: # ledger
        id_cols = ["ledger_id", "id", "invoice_id"]
        date_cols = ["transaction_date", "date"]
        amount_cols = ["amount"]
        utr_cols = ["utr"]

    seen_ids = set()
    duplicates_count = 0
    
    valid_indices = []

    for i, row in df.iterrows():
        row_errors = []
        is_invalid = False
        row_num = i + 2 # 1-indexed, +1 for header
        
        # Check ID
        missing_id, val_id = _check_missing(row, id_cols)
        if missing_id:
            row_errors.append({"source": source_type, "row": row_num, "field": id_cols[0], "value": "", "error": f"{id_cols[0]} is required."})
            is_invalid = True
        else:
            val_id_str = str(val_id).strip()
            if val_id_str in seen_ids:
                row_errors.append({"source": source_type, "row": row_num, "field": id_cols[0], "value": val_id_str, "error": f"Duplicate {id_cols[0]} detected."})
                duplicates_count += 1
                # Duplicates are considered a data quality issue for the UI, but we don't necessarily reject the row just because it's a duplicate.
                # However, the prompt says "Do not automatically delete duplicates. Pass them to reconciliation/exception handling."
            else:
                seen_ids.add(val_id_str)

        # Check Date
        missing_date, val_date = _check_missing(row, date_cols)
        if missing_date:
            row_errors.append({"source": source_type, "row": row_num, "field": date_cols[0], "value": "", "error": f"{date_cols[0]} is required."})
            is_invalid = True
            
        # Check Amount
        missing_amount, val_amount = _check_missing(row, amount_cols)
        if missing_amount:
            row_errors.append({"source": source_type, "row": row_num, "field": amount_cols[0], "value": "", "error": f"{amount_cols[0]} is required."})
            is_invalid = True
        else:
            try:
                float(val_amount)
            except (ValueError, TypeError):
                row_errors.append({"source": source_type, "row": row_num, "field": amount_cols[0], "value": str(val_amount), "error": "Amount must be numeric."})
                is_invalid = True
                
        # UTR is highly recommended but if we absolutely require it, let's flag if missing. The prompt said "empty UTR where UTR is required", but usually UTR is required for bank and settlement. Let's make it required.
        missing_utr, val_utr = _check_missing(row, utr_cols)
        if missing_utr:
            row_errors.append({"source": source_type, "row": row_num, "field": "utr", "value": "", "error": "UTR is missing."})
            is_invalid = True

        if is_invalid:
            invalid += 1
            errors.extend(row_errors)
        else:
            valid += 1
            valid_indices.append(i)
            
    # Generate Preview (first 5 valid rows or first 5 overall if no valid)
    preview_df = df.iloc[valid_indices].head(5) if len(valid_indices) > 0 else df.head(5)
    # Replace NaNs with None for JSON serialization
    preview_df = preview_df.where(pd.notnull(preview_df), None)
    
    return {
        "records": total_records,
        "valid_records": valid,
        "invalid_records": invalid,
        "duplicates": duplicates_count,
        "errors": errors[:50],  # Cap errors to avoid huge payloads
        "preview": preview_df.to_dict(orient="records"),
        "valid_indices": valid_indices
    }
