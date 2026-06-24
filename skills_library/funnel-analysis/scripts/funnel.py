def generate_df(ds_clients, excel_files, *args, **kwargs):
    """Funnel conversion + drop-off between stages.

    Reads (user_id, step) from the connected data source when present, else a
    synthetic sample. Returns tidy: step, step_index, users,
    conversion_from_prev_pct, overall_pct, drop_off — one row per funnel step,
    in funnel order.
    """
    import pandas as pd

    # --- canonical funnel ORDER (configurable: edit this list to match your
    #     product's stages; per-step user counts are derived against it) ---
    STEPS = ["Visit", "SignUp", "AddToCart", "Checkout", "Purchase"]

    counts = None  # dict: step -> unique user count
    # If the analysis needs a join/aggregation, the agent passes rows via sql= -> input_df.
    _df = kwargs.get('input_df')
    _raw_df = _df if (_df is not None and len(_df) > 0) else None

    # --- real data path: discover tables via schema introspection ---
    if (_raw_df is None or len(_raw_df) == 0) and ds_clients:
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
                            _raw_df = candidate
                            print("loaded table:", tname, "rows:", len(_raw_df))
                            break
                    except Exception:
                        continue
                if _raw_df is not None and len(_raw_df) > 0:
                    break
            except Exception:
                continue

    # --- Excel fallback ---
    if (_raw_df is None or len(_raw_df) == 0) and excel_files:
        try:
            first = list(excel_files.values())[0] if isinstance(excel_files, dict) else excel_files[0]
            _raw_df = first if isinstance(first, pd.DataFrame) else None
        except Exception:
            _raw_df = None

    # --- FAIL LOUD: no synthetic fallback ---
    if _raw_df is None or len(_raw_df) == 0:
        raise RuntimeError(
            "Funnel analysis script could not load any data: no connected data "
            "source returned rows and no Excel file was provided. Connect a data "
            "source with at least one non-empty table (expected columns: user_id, "
            "step) before running this skill."
        )

    # Require key columns
    if "user_id" not in _raw_df.columns or "step" not in _raw_df.columns:
        raise RuntimeError(
            "Funnel analysis requires columns 'user_id' and 'step'. "
            "Found: {}. Rename or map your columns accordingly.".format(list(_raw_df.columns))
        )

    # Derive counts from real data
    per_step = _raw_df.groupby("step")["user_id"].nunique()
    counts = {s: int(per_step.get(s, 0)) for s in STEPS}
    for s in per_step.index:
        if s not in counts:
            counts[s] = int(per_step[s])
    # Remove zero-count steps not in STEPS so output is clean
    counts = {k: v for k, v in counts.items() if v > 0}

    order = list(counts.keys())
    rows = []
    first_users = counts[order[0]] if counts[order[0]] else 1
    prev_users = None
    for idx, step in enumerate(order):
        users = counts[step]
        conv_prev = (
            round(users / prev_users * 100, 1) if prev_users else 100.0
        )
        overall = round(users / first_users * 100, 1)
        drop = (prev_users - users) if prev_users is not None else 0
        rows.append(
            {
                "step": step,
                "step_index": idx,
                "users": users,
                "conversion_from_prev_pct": conv_prev,
                "overall_pct": overall,
                "drop_off": drop,
            }
        )
        prev_users = users

    out = pd.DataFrame(
        rows,
        columns=[
            "step",
            "step_index",
            "users",
            "conversion_from_prev_pct",
            "overall_pct",
            "drop_off",
        ],
    )
    print("steps:", len(out), "top:", out["users"].iloc[0], "end:", out["users"].iloc[-1])
    return out
