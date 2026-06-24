def generate_df(ds_clients, excel_files, *args, **kwargs):
    """Anomaly detection on a numeric time/series column.

    Reads (order_date, amount) from the connected data source when present,
    else a synthetic daily series with planted spikes/dips. Returns the FULL
    series sorted by period with flags: value, z_score, is_anomaly, method,
    direction — so the agent can chart it and read off the outliers.
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
            "Anomaly detection script could not load any data: no connected data "
            "source returned rows and no Excel file was provided. Connect a data "
            "source with at least one non-empty table before running this skill."
        )

    # --- normalize: a period column + a numeric value column ---
    # prefer literal 'item'/'value' columns (supplied via input_df) when present
    if "value" in df.columns:
        value_col = "value"
    else:
        value_col = "amount" if "amount" in df.columns else df.columns[-1]
    if "item" in df.columns:
        period_col = "item"
    else:
        period_col = "order_date" if "order_date" in df.columns else df.columns[0]

    df = df[[period_col, value_col]].copy()
    df.columns = ["period", "value"]
    df["value"] = pd.to_numeric(df["value"], errors="coerce")
    df = df.dropna(subset=["value"])

    # try to treat the period as a date for clean sorting; fall back as-is
    parsed = pd.to_datetime(df["period"], errors="coerce")
    if parsed.notna().any():
        df["period"] = parsed
    df = df.sort_values("period").reset_index(drop=True)

    values = df["value"]
    mean = float(values.mean())
    std = float(values.std(ddof=0))

    # --- method 1: z-score (guard std == 0) ---
    if std == 0:
        df["z_score"] = 0.0
    else:
        df["z_score"] = ((df["value"] - mean) / std).round(2)
    z_thresh = float(kwargs.get("z_thresh", 3.0))
    z_anom = df["z_score"].abs() >= z_thresh

    # --- method 2: IQR outliers (secondary) ---
    q1 = float(values.quantile(0.25))
    q3 = float(values.quantile(0.75))
    iqr = q3 - q1
    low = q1 - 1.5 * iqr
    high = q3 + 1.5 * iqr
    iqr_anom = (df["value"] < low) | (df["value"] > high)

    # --- combine: flag + which method(s) + direction ---
    df["is_anomaly"] = z_anom | iqr_anom

    def _method(i):
        m = []
        if bool(z_anom.iloc[i]):
            m.append("zscore")
        if bool(iqr_anom.iloc[i]):
            m.append("iqr")
        return "+".join(m)

    df["method"] = [_method(i) for i in range(len(df))]
    df["direction"] = np.where(
        df["is_anomaly"] & (df["value"] >= mean),
        "spike",
        np.where(df["is_anomaly"], "dip", ""),
    )

    out = df[
        ["period", "value", "z_score", "is_anomaly", "method", "direction"]
    ].reset_index(drop=True)
    n_anom = int(out["is_anomaly"].sum())
    print("rows:", len(out), "anomalies:", n_anom)
    return out
