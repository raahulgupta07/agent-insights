"""Plain self-test for the Smart Upload classifier (NOT pytest).

Writes a few synthetic files to a temp dir and runs ``sniff_file`` on each, then
runs ``classify_batch`` (heuristic-only, llm=None) over the lot. Prints the
destination + confidence + needs_confirm so routing can be eyeballed.

Run:
    cd backend && PYTHONPATH=. python3 app/services/smart_upload/_selftest.py
"""

import asyncio
import os
import sys
import tempfile

# Allow running directly from the repo without installing the package.
_HERE = os.path.dirname(os.path.abspath(__file__))
_BACKEND = os.path.abspath(os.path.join(_HERE, "..", "..", ".."))
if _BACKEND not in sys.path:
    sys.path.insert(0, _BACKEND)

from app.services.smart_upload.classifier import sniff_file, classify_batch  # noqa: E402


def _write(d, name, content):
    p = os.path.join(d, name)
    with open(p, "w", encoding="utf-8") as fh:
        fh.write(content)
    return p


def build_cases(d):
    cases = []

    # 1. Tabular CSV -> database (10 rows, numeric measure column).
    rows = ["region,month,units_sold,revenue"]
    for i in range(10):
        rows.append(f"R{i%3},2026-{(i%12)+1:02d},{100+i*7},{1000.5+i*33}")
    cases.append(("sales.csv", _write(d, "sales.csv", "\n".join(rows))))

    # 2. Two-column glossary -> semantic.
    gloss = "term,meaning\n"
    gloss += "GMV,Gross merchandise value: total sales before returns and fees\n"
    gloss += "AOV,Average order value computed as revenue divided by orders\n"
    gloss += "Churn,Share of customers who stopped buying in the period\n"
    gloss += "MRR,Monthly recurring revenue from active subscriptions\n"
    cases.append(("data_dictionary.csv", _write(d, "data_dictionary.csv", gloss)))

    # 3. Rules / logic prose -> instructions.
    rules = (
        "Active customer = purchased in the last 90 days AND not refunded.\n"
        "Always filter out test accounts where email contains '@example.com'.\n"
        "Net revenue must exclude tax and shipping.\n"
        "Exclude internal orders from all sales reports.\n"
    )
    cases.append(("business_logic.txt", _write(d, "business_logic.txt", rules)))

    # 4. Q&A pairs -> examples.
    qa = (
        "Q: What were total sales last month?\n"
        "A: SELECT SUM(revenue) FROM sales WHERE month = last_month;\n\n"
        "Q: Who are the top 5 customers by revenue?\n"
        "A: SELECT customer, SUM(revenue) FROM sales GROUP BY customer "
        "ORDER BY 2 DESC LIMIT 5;\n"
    )
    cases.append(("qa_examples.txt", _write(d, "qa_examples.txt", qa)))

    # 5. Narrative prose -> knowledge.
    narr = (
        "The company was founded in 2014 and operates across three regions. "
        "Our retail strategy focuses on neighbourhood convenience stores and "
        "a growing online channel. This document describes the operating model "
        "and the history of the business in general terms for reference.\n"
    ) * 3
    cases.append(("company_overview.txt", _write(d, "company_overview.txt", narr)))

    return cases


def main():
    with tempfile.TemporaryDirectory() as d:
        cases = build_cases(d)

        print("=== sniff_file (heuristic) ===")
        files = []
        for name, path in cases:
            rec = sniff_file(path, name)
            files.append({"path": path, "filename": name})
            print(f"{name:24s} -> {rec['dest']:12s} "
                  f"conf={rec['confidence']:3d} sink={rec['sink']:16s} "
                  f"confirm={_cf(rec)}  | {rec['reason']}")

        print("\n=== classify_batch (llm=None, heuristic-only) ===")
        records = asyncio.run(classify_batch(files, llm=None))
        for rec in records:
            print(f"{rec['filename']:24s} -> {rec['dest']:12s} "
                  f"conf={rec['confidence']:3d} "
                  f"needs_confirm={rec['needs_confirm']} "
                  f"source={rec['source']}")


def _cf(rec):
    # sniff_file does not stamp needs_confirm; show the policy result.
    from app.services.smart_upload.classifier import _needs_confirm
    return _needs_confirm(rec)


if __name__ == "__main__":
    main()
