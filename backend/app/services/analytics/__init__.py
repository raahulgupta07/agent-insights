"""Analytics services for the BI uplift (compute-then-narrate).

`compute.py` holds DETERMINISTIC aggregates (pure pandas/numpy — no LLM, no
network). Every BI-uplift phase reuses it so the numbers are always real and
the model only ever interprets them. Fail-soft by contract: helpers return
partial/empty structures rather than raising.
"""
