def generate_df(ds_clients, excel_files, *args, **kwargs):
    """Monthly time-series trend.

    Reads (order_date, amount) from the connected data source when present,
    else a synthetic 12+ month sample. Resamples to monthly and returns tidy:
    period, value, mom_pct, yoy_pct, roll3.
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
            "Time-series trend script could not load any data: no connected data "
            "source returned rows and no Excel file was provided. Connect a data "
            "source with at least one non-empty table before running this skill."
        )

    # normalize the two working columns (date + numeric value)
    # prefer literal 'item'/'value' columns (supplied via input_df) when present
    date_col = "item" if "item" in df.columns else df.columns[0]
    if "value" in df.columns:
        val_col = "value"
    else:
        val_col = df.columns[1] if len(df.columns) > 1 else df.columns[0]
    work = pd.DataFrame(
        {
            "order_date": pd.to_datetime(df[date_col], errors="coerce"),
            "amount": pd.to_numeric(df[val_col], errors="coerce"),
        }
    ).dropna(subset=["order_date"])

    # resample to monthly sum
    monthly = (
        work.set_index("order_date")["amount"]
        .resample("MS")
        .sum()
        .rename("value")
        .reset_index()
    )
    monthly["period"] = monthly["order_date"].dt.strftime("%Y-%m")
    monthly = monthly.sort_values("order_date").reset_index(drop=True)

    # month-over-month % change (vs previous row)
    monthly["mom_pct"] = (monthly["value"].pct_change() * 100).round(1)

    # year-over-year % change (vs 12 months prior; null when not available)
    monthly["yoy_pct"] = (monthly["value"].pct_change(periods=12) * 100).round(1)

    # 3-month moving average
    monthly["roll3"] = (
        monthly["value"].rolling(window=3, min_periods=1).mean().round(2)
    )

    out = monthly[["period", "value", "mom_pct", "yoy_pct", "roll3"]].sort_values(
        "period"
    ).reset_index(drop=True)
    print("months:", len(out), "span:", out["period"].iloc[0], "->", out["period"].iloc[-1])
    return out
