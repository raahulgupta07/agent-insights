def generate_df(ds_clients, excel_files, *args, **kwargs):
    """Programmatic EDA: per-column profile with sanity checks.

    Profiles whatever the data source returns (first 5000 rows of the first
    available table) or an Excel sheet. Discovers available tables via
    get_schemas() — never assumes a hardcoded table name. Raises RuntimeError
    if no data can be loaded so the agent sees a clear failure instead of
    silently analyzing fabricated data.

    For every column: dtype, non-null, null %, distinct count, sample value,
    and numeric stats (min/mean/max/std) when applicable. pandas/numpy only
    — AST-safe.
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
            "EDA script could not load any data: no connected data source returned rows "
            "and no Excel file was provided. Connect a data source with at least one "
            "non-empty table before running this skill."
        )

    rows = []
    n = len(df)
    for col in df.columns:
        s = df[col]
        non_null = int(s.notna().sum())
        null_pct = round((1 - non_null / n) * 100, 1) if n else 0.0
        distinct = int(s.nunique(dropna=True))
        sample = s.dropna().iloc[0] if non_null else None
        rec = {
            "column": str(col),
            "dtype": str(s.dtype),
            "non_null": non_null,
            "null_pct": null_pct,
            "distinct": distinct,
            "sample": str(sample)[:40] if sample is not None else "",
            "min": "", "mean": "", "max": "", "std": "",
        }
        num = pd.to_numeric(s, errors="coerce")
        if num.notna().sum() > 0 and s.dtype.kind in "ifu":
            rec["min"] = round(float(num.min()), 2)
            rec["mean"] = round(float(num.mean()), 2)
            rec["max"] = round(float(num.max()), 2)
            rec["std"] = round(float(num.std(ddof=0)), 2)
        rows.append(rec)

    out = pd.DataFrame(rows)
    print(f"profiled {len(out)} columns over {n} rows")
    return out
