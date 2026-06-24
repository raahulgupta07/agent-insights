def generate_df(ds_clients, excel_files, *args, **kwargs):
    """A/B test: conversion rate per variant, lift, two-proportion z-test.

    Reads (variant, converted) rows from the data source when present, else a
    synthetic sample. converted is 0/1. Returns one row per variant plus a
    summary row with lift, z-score, p-value, and a 95% significance flag.
    numpy/math only (no scipy) so it passes the sandbox AST gate.
    """
    import math
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
            "A/B test script could not load any data: no connected data source "
            "returned rows and no Excel file was provided. Connect a data source "
            "with at least one non-empty table (expected columns: variant, converted) "
            "before running this skill."
        )

    # Require 'variant' and 'converted' columns
    if "variant" not in df.columns or "converted" not in df.columns:
        raise RuntimeError(
            "A/B test requires columns 'variant' and 'converted' in the data. "
            "Found columns: {}. Rename or map your columns accordingly.".format(
                list(df.columns)
            )
        )

    df = df[["variant", "converted"]].copy()
    df["converted"] = pd.to_numeric(df["converted"], errors="coerce").fillna(0)

    g = df.groupby("variant")["converted"].agg(n="count", conversions="sum")
    g["rate_pct"] = (g["conversions"] / g["n"] * 100).round(2)
    g = g.sort_values("variant").reset_index()

    out_rows = g.to_dict("records")

    # two-proportion z-test on the first two variants (control=first)
    if len(g) >= 2:
        n1, c1 = g.loc[0, "n"], g.loc[0, "conversions"]
        n2, c2 = g.loc[1, "n"], g.loc[1, "conversions"]
        p1, p2 = c1 / n1, c2 / n2
        pool = (c1 + c2) / (n1 + n2)
        se = math.sqrt(pool * (1 - pool) * (1 / n1 + 1 / n2)) or 1e-9
        z = (p2 - p1) / se
        # two-sided p from the standard normal CDF via erf
        p_value = 2 * (1 - 0.5 * (1 + math.erf(abs(z) / math.sqrt(2))))
        lift_pct = ((p2 - p1) / p1 * 100) if p1 else 0.0
        out_rows.append(
            {
                "variant": f"{g.loc[1,'variant']} vs {g.loc[0,'variant']}",
                "n": int(n1 + n2),
                "conversions": int(c1 + c2),
                "rate_pct": round(lift_pct, 2),     # reuse col = lift% on summary row
                "z_score": round(z, 3),
                "p_value": round(p_value, 4),
                "significant_95": bool(abs(z) > 1.96),
            }
        )
        print(f"lift {lift_pct:.1f}%  z={z:.2f}  p={p_value:.4f}  "
              f"sig={'YES' if abs(z) > 1.96 else 'no'}")

    out = pd.DataFrame(out_rows)
    return out
