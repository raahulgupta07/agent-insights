def generate_df(ds_clients, excel_files, *args, **kwargs):
    """Pareto 80/20: rank items, cumulative share, flag the vital few."""
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
            "Pareto analysis script could not load any data: no connected data "
            "source returned rows and no Excel file was provided. Connect a data "
            "source with at least one non-empty table (expected columns: item/name "
            "and a numeric value column) before running this skill."
        )

    # Use 'item'+'value' if available; otherwise auto-detect: first str col = item, first numeric = value
    if "item" in df.columns and "value" in df.columns:
        df = df[["item", "value"]].copy()
    else:
        # Auto-detect item (first object/string col) and value (first numeric col)
        str_cols = [c for c in df.columns if df[c].dtype == object or str(df[c].dtype) == 'category']
        num_cols = [c for c in df.columns if str(df[c].dtype).startswith(('int', 'float'))]
        if not str_cols or not num_cols:
            raise RuntimeError(
                "Pareto analysis requires at least one categorical column (item) and one "
                "numeric column (value). Found columns: {}.".format(list(df.columns))
            )
        df = df[[str_cols[0], num_cols[0]]].copy()
        df.columns = ["item", "value"]
        print("auto-detected columns: item={}, value={}".format(str_cols[0], num_cols[0]))
    df["value"] = pd.to_numeric(df["value"], errors="coerce").fillna(0)
    df = df.sort_values("value", ascending=False).reset_index(drop=True)

    total = df["value"].sum() or 1
    df["share_pct"] = (df["value"] / total * 100).round(2)
    df["cum_pct"] = df["share_pct"].cumsum().round(2)
    # vital few = rows up to and including the one that crosses 80%
    crossed = df["cum_pct"] >= 80
    cutoff = crossed.idxmax() if crossed.any() else len(df) - 1
    df["vital_few"] = df.index <= cutoff

    n_vital = int(df["vital_few"].sum())
    print(f"vital few: {n_vital}/{len(df)} items drive ~80% of {total:.0f}")
    return df
