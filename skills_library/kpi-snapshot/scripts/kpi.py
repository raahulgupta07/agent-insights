def generate_df(ds_clients, excel_files, *args, **kwargs):
    """KPI snapshot — current-period headline metrics vs the prior period.

    Reads (order_date, amount) from the connected data source when present,
    else a synthetic sample spanning at least two months. Splits into the
    latest month (current) vs the month before (prior) and returns one row
    per KPI: kpi, current, prior, delta, delta_pct, direction.
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
            "KPI snapshot script could not load any data: no connected data source "
            "returned rows and no Excel file was provided. Connect a data source with "
            "at least one non-empty table (expected columns: order_date, amount) "
            "before running this skill."
        )

    # Require key columns
    missing = [c for c in ["order_date", "amount"] if c not in df.columns]
    if missing:
        raise RuntimeError(
            "KPI snapshot requires columns: order_date, amount. "
            "Missing: {}. Found: {}.".format(missing, list(df.columns))
        )

    df["order_date"] = pd.to_datetime(df["order_date"])
    df["amount"] = pd.to_numeric(df["amount"], errors="coerce")
    df = df.dropna(subset=["order_date", "amount"])
    df["order_month"] = df["order_date"].dt.to_period("M")

    months = sorted(df["order_month"].unique())
    cur_p = months[-1]
    prior_p = months[-2] if len(months) >= 2 else None

    cur = df[df["order_month"] == cur_p]
    prior = df[df["order_month"] == prior_p] if prior_p is not None else df.iloc[0:0]

    def _val(frame, kind):
        if kind == "Total":
            return float(frame["amount"].sum())
        if kind == "Orders":
            return float(len(frame))
        if kind == "Avg Order Value":
            return float(frame["amount"].mean()) if len(frame) else 0.0
        return 0.0

    rows = []
    for kpi in ["Total", "Orders", "Avg Order Value"]:
        current = round(_val(cur, kpi), 2)
        prior_v = round(_val(prior, kpi), 2)
        delta = round(current - prior_v, 2)
        if prior_v != 0:
            delta_pct = round((delta / prior_v) * 100, 1)
        else:
            delta_pct = None
        if delta > 0:
            direction = "up"
        elif delta < 0:
            direction = "down"
        else:
            direction = "flat"
        rows.append(
            {
                "kpi": kpi,
                "current": current,
                "prior": prior_v,
                "delta": delta,
                "delta_pct": delta_pct,
                "direction": direction,
            }
        )

    out = pd.DataFrame(
        rows, columns=["kpi", "current", "prior", "delta", "delta_pct", "direction"]
    )
    print(
        "kpi-snapshot:", len(out), "KPIs |",
        "current month", str(cur_p),
        "vs prior", str(prior_p),
    )
    return out
