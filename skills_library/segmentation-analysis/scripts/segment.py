def generate_df(ds_clients, excel_files, *args, **kwargs):
    """Customer segmentation by spend + frequency (quantile rule-based).

    Reads (customer_id, orders, spend) from the data source when present, else a
    synthetic sample. Buckets each customer High/Mid/Low on spend and frequency
    via tertiles, names the combined segment, and returns per-segment profiles.
    pandas/numpy only (no sklearn) — deterministic, AST-safe.
    """
    import pandas as pd
    import numpy as np

    # If the analysis needs a join/aggregation, the agent passes rows via sql= -> input_df.
    _df = kwargs.get('input_df')
    df = _df if (_df is not None and len(_df) > 0) else None

    # --- real data path: discover tables via schema introspection ---
    if (df is None or len(df) == 0) and ds_clients:
        for client_key, client in ds_clients.items():
            try:
                tables = client.get_schemas()
                if not tables:
                    continue
                for table in tables:
                    tname = table.name if 'name' in dir(table) else str(table)
                    if not tname:
                        continue
                    try:
                        candidate = client.execute_query(
                            'SELECT * FROM "{}" LIMIT 5000'.format(tname)
                        )
                        if candidate is not None and len(candidate) > 0:
                            df = candidate
                            print("loaded table:", tname, "rows:", len(df))
                            break
                    except Exception:
                        continue
                if df is not None and len(df) > 0:
                    break
            except Exception:
                continue

    # --- Excel fallback ---
    if (df is None or len(df) == 0) and excel_files:
        try:
            first = list(excel_files.values())[0] if isinstance(excel_files, dict) else excel_files[0]
            df = first if isinstance(first, pd.DataFrame) else None
        except Exception:
            df = None

    # --- FAIL LOUD: no synthetic fallback ---
    if df is None or len(df) == 0:
        raise RuntimeError(
            "Segmentation analysis script could not load any data: no connected data "
            "source returned rows and no Excel file was provided. Connect a data "
            "source with at least one non-empty table (expected columns: customer_id, "
            "orders, spend) before running this skill."
        )

    # Require key columns
    missing = [c for c in ["customer_id", "orders", "spend"] if c not in df.columns]
    if missing:
        raise RuntimeError(
            "Segmentation analysis requires columns: customer_id, orders, spend. "
            "Missing: {}. Found: {}.".format(missing, list(df.columns))
        )

    df = df[["customer_id", "orders", "spend"]].copy()
    df["orders"] = pd.to_numeric(df["orders"], errors="coerce").fillna(0)
    df["spend"] = pd.to_numeric(df["spend"], errors="coerce").fillna(0)

    def tertile(s):
        # rank-based tertile so ties/duplicate edges don't collapse bins
        r = s.rank(method="first", pct=True)
        return np.where(r > 2 / 3, "High", np.where(r > 1 / 3, "Mid", "Low"))

    df["spend_band"] = tertile(df["spend"])
    df["freq_band"] = tertile(df["orders"])

    name_map = {
        ("High", "High"): "Champions",
        ("High", "Mid"): "Big Spenders",
        ("High", "Low"): "Whales (rare)",
        ("Mid", "High"): "Loyal Regulars",
        ("Mid", "Mid"): "Core",
        ("Mid", "Low"): "Promising",
        ("Low", "High"): "Frequent Low-Value",
        ("Low", "Mid"): "Casual",
        ("Low", "Low"): "At Risk / Dormant",
    }
    df["segment"] = [
        name_map[(s, f)] for s, f in zip(df["spend_band"], df["freq_band"])
    ]

    prof = (
        df.groupby("segment")
        .agg(
            customers=("customer_id", "nunique"),
            avg_orders=("orders", "mean"),
            avg_spend=("spend", "mean"),
            total_spend=("spend", "sum"),
        )
        .reset_index()
    )
    total = prof["total_spend"].sum() or 1
    prof["pct_of_revenue"] = (prof["total_spend"] / total * 100).round(1)
    prof["avg_orders"] = prof["avg_orders"].round(2)
    prof["avg_spend"] = prof["avg_spend"].round(2)
    prof = prof.sort_values("total_spend", ascending=False).reset_index(drop=True)

    print(f"{len(prof)} segments over {df['customer_id'].nunique()} customers")
    return prof
