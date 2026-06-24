def generate_df(ds_clients, excel_files, *args, **kwargs):
    """Standard business metrics + benchmark status.

    Reads (order_id, customer_id, amount) from the data source when present,
    else a synthetic sample. Computes revenue, orders, customers, AOV, repeat
    rate, revenue/customer. Each metric is compared to a simple benchmark and
    flagged above/below. pandas/numpy only — AST-safe.
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
            "Business metrics script could not load any data: no connected data "
            "source returned rows and no Excel file was provided. Connect a data "
            "source with at least one non-empty table (expected columns: order_id, "
            "customer_id, amount) before running this skill."
        )

    # Require key columns
    missing = [c for c in ["order_id", "customer_id", "amount"] if c not in df.columns]
    if missing:
        raise RuntimeError(
            "Business metrics requires columns: order_id, customer_id, amount. "
            "Missing: {}. Found: {}.".format(missing, list(df.columns))
        )

    df = df[["order_id", "customer_id", "amount"]].copy()
    df["amount"] = pd.to_numeric(df["amount"], errors="coerce").fillna(0)

    revenue = float(df["amount"].sum())
    orders = int(df["order_id"].nunique())
    customers = int(df["customer_id"].nunique())
    aov = revenue / orders if orders else 0.0
    rev_per_cust = revenue / customers if customers else 0.0
    per_cust_orders = df.groupby("customer_id")["order_id"].nunique()
    repeat_rate = float((per_cust_orders > 1).mean() * 100)

    # benchmarks (illustrative targets; tune per business)
    rows = [
        ("Total Revenue", round(revenue, 2), None, ""),
        ("Orders", orders, None, ""),
        ("Customers", customers, None, ""),
        ("Avg Order Value", round(aov, 2), 75.0, ""),
        ("Revenue / Customer", round(rev_per_cust, 2), 200.0, ""),
        ("Repeat Rate %", round(repeat_rate, 1), 30.0, ""),
    ]
    out = pd.DataFrame(rows, columns=["metric", "value", "benchmark", "status"])

    def status(v, b):
        if b is None:
            return "—"
        return "above" if v >= b else "below"

    out["status"] = [status(v, b) for v, b in zip(out["value"], out["benchmark"])]
    print(f"revenue {revenue:,.0f} · orders {orders} · AOV {aov:.2f} · "
          f"repeat {repeat_rate:.0f}%")
    return out
