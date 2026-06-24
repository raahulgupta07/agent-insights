def generate_df(ds_clients, excel_files, *args, **kwargs):
    """RFM customer segmentation.

    Reads (customer_id, order_date, amount) from the connected data source when
    present, else a synthetic sample. Per customer computes Recency (days since
    last order vs the max date in the data), Frequency (order count) and Monetary
    (total amount), scores each 1-5 by quantile, and assigns an actionable segment.
    Returns one row per customer: customer_id, recency_days, frequency, monetary,
    r, f, m, segment.
    """
    import pandas as pd

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
            "RFM segmentation script could not load any data: no connected data "
            "source returned rows and no Excel file was provided. Connect a data "
            "source with at least one non-empty table (expected columns: "
            "customer_id, order_date, amount) before running this skill."
        )

    # Require key columns
    missing = [c for c in ["customer_id", "order_date", "amount"] if c not in df.columns]
    if missing:
        raise RuntimeError(
            "RFM segmentation requires columns: customer_id, order_date, amount. "
            "Missing: {}. Found: {}.".format(missing, list(df.columns))
        )

    df["order_date"] = pd.to_datetime(df["order_date"])
    df["amount"] = pd.to_numeric(df["amount"], errors="coerce").fillna(0)

    # reference "today" = the most recent order date in the data
    as_of = df["order_date"].max()

    rfm = df.groupby("customer_id").agg(
        last_order=("order_date", "max"),
        frequency=("order_date", "count"),
        monetary=("amount", "sum"),
    ).reset_index()
    rfm["recency_days"] = (as_of - rfm["last_order"]).dt.days

    # --- 1-5 quantile scores (guard tiny samples / no spread) ---
    def _score(series, reverse=False):
        labels = [5, 4, 3, 2, 1] if reverse else [1, 2, 3, 4, 5]
        n_unique = series.nunique()
        if n_unique < 2:
            return pd.Series([3] * len(series), index=series.index)
        bins = min(5, n_unique)
        use_labels = labels[:bins] if not reverse else labels[-bins:]
        try:
            q = pd.qcut(series, q=bins, labels=use_labels, duplicates="drop")
            return q.astype("Int64").astype(int)
        except Exception:
            return pd.Series([3] * len(series), index=series.index)

    # lower recency_days is better → reverse so recent = high R
    rfm["r"] = _score(rfm["recency_days"], reverse=True)
    rfm["f"] = _score(rfm["frequency"])
    rfm["m"] = _score(rfm["monetary"])

    def _segment(row):
        r, f, m = row["r"], row["f"], row["m"]
        if r >= 4 and f >= 4:
            return "Champions"
        if f >= 4:
            return "Loyal"
        if m >= 4:
            return "Big Spenders"
        if r <= 2 and f >= 3:
            return "At Risk"
        if r >= 4 and f <= 2:
            return "New"
        return "Others"

    rfm["segment"] = rfm.apply(_segment, axis=1)

    out = rfm[
        ["customer_id", "recency_days", "frequency", "monetary", "r", "f", "m", "segment"]
    ].sort_values(["segment", "monetary"], ascending=[True, False]).reset_index(drop=True)
    out["monetary"] = out["monetary"].round(2)

    print(
        "customers:", len(out),
        "segments:", out["segment"].nunique(),
        "champions:", int((out["segment"] == "Champions").sum()),
    )
    return out
