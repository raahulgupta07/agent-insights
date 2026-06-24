def generate_df(ds_clients, excel_files, *args, **kwargs):
    """Cohort retention matrix.

    Reads (customer_id, order_date) from the connected data source when present,
    else a synthetic sample. Returns tidy: cohort, month_index, active, retention_pct.
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
            "Cohort retention script could not load any data: no connected data "
            "source returned rows and no Excel file was provided. Connect a data "
            "source with at least one non-empty table (expected columns: "
            "customer_id, order_date) before running this skill."
        )

    # Require key columns
    missing = [c for c in ["customer_id", "order_date"] if c not in df.columns]
    if missing:
        raise RuntimeError(
            "Cohort retention requires columns: customer_id, order_date. "
            "Missing: {}. Found: {}.".format(missing, list(df.columns))
        )

    df["order_date"] = pd.to_datetime(df["order_date"])
    df["order_month"] = df["order_date"].dt.to_period("M")
    cohort = df.groupby("customer_id")["order_month"].min().rename("cohort")
    df = df.join(cohort, on="customer_id")
    df["month_index"] = (
        (df["order_month"] - df["cohort"]).apply(lambda x: x.n)
    )

    sizes = df.groupby("cohort")["customer_id"].nunique().rename("cohort_size")
    active = (
        df.groupby(["cohort", "month_index"])["customer_id"]
        .nunique()
        .rename("active")
        .reset_index()
    )
    active = active.join(sizes, on="cohort")
    active["retention_pct"] = (
        active["active"] / active["cohort_size"] * 100
    ).round(1)
    active["cohort"] = active["cohort"].astype(str)

    out = active[["cohort", "month_index", "active", "retention_pct"]].sort_values(
        ["cohort", "month_index"]
    ).reset_index(drop=True)
    print("cohorts:", out["cohort"].nunique(), "rows:", len(out))
    return out
