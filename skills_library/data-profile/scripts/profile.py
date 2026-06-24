def generate_df(ds_clients, excel_files, *args, **kwargs):
    """Per-column data profile.

    Discovers available tables via get_schemas() — never assumes a hardcoded
    table name. Loads the first non-empty table from a connected data source,
    or an Excel sheet. Returns ONE row per column with:
    column, dtype, non_null, null_pct, distinct, sample_value.

    Raises RuntimeError if no data can be loaded so the agent sees a clear
    failure instead of silently analyzing fabricated data.
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
            "Data profile script could not load any data: no connected data source "
            "returned rows and no Excel file was provided. Connect a data source with "
            "at least one non-empty table before running this skill."
        )

    rows = []
    n = len(df)
    for c in df.columns:
        col = df[c]
        non_null = int(col.notna().sum())
        null_pct = round(float(col.isna().mean()) * 100, 1) if n else 0.0
        non_null_vals = col.dropna()
        sample = str(non_null_vals.iloc[0]) if len(non_null_vals) else ""
        rows.append(
            {
                "column": str(c),
                "dtype": str(col.dtype),
                "non_null": non_null,
                "null_pct": null_pct,
                "distinct": int(col.nunique()),
                "sample_value": sample,
            }
        )

    out = pd.DataFrame(
        rows,
        columns=["column", "dtype", "non_null", "null_pct", "distinct", "sample_value"],
    )
    print("profiled columns:", len(out), "over rows:", n)
    return out
