"""Regression guard for the scoped SQL-write validator.

Background: the validator used to scan EVERY python string literal for SQL
keywords, so a data column named "Successful Call Rate (%)" tripped the
`CALL <name>(` pattern and blocked an entirely read-only report. The fix scopes
the scan to SQL-executor call-sites only. These tests lock that behaviour in:

  * data literals (column aliases, titles, dict keys) are ALWAYS allowed,
    regardless of the SQL-ish words inside them;
  * real write SQL handed to an executor is STILL blocked.

If a future edit re-broadens the scan, the ALLOWED cases fail here.
"""

import pytest

from app.ai.code_execution.code_execution import (
    validate_python_code,
    UnsafePythonError,
)


def _is_blocked(code: str) -> bool:
    try:
        validate_python_code(code)
        return False
    except UnsafePythonError:
        return True


# --- Data literals that previously false-positived -------------------------
# Each is a column alias / title / key containing a SQL-ish word. None of these
# is executed SQL, so every one must be ALLOWED.
ALLOWED_DATA_LITERALS = [
    'df = con.execute_query(\'SELECT x AS "Successful Call Rate (%)" FROM t\')',
    'title = "Successful Call Rate (%) by Brand"',
    'cols = {"Call Rate (sec)": 1, "Load Time (ms)": 2, "Grant Amount": 3}',
    'label = "Replace Old Stock"',
    'note = "Please update the description and create a chart"',
    'metric = "Merge Conflicts (count)"',
    'header = "Drop-off Rate (%)"',
    'k = "Truncate Long Names"',
]


@pytest.mark.parametrize("code", ALLOWED_DATA_LITERALS)
def test_data_literals_are_allowed(code):
    assert not _is_blocked(code), f"data literal wrongly blocked: {code!r}"


# --- Real write SQL at an executor call-site: must stay BLOCKED -------------
BLOCKED_WRITE_SQL = [
    'con.execute_query("DROP TABLE users")',
    'con.execute("INSERT INTO t VALUES (1)")',
    'con.execute("UPDATE accounts SET balance = 0")',
    'con.execute_query("DELETE FROM orders")',
    'con.sql("CREATE TABLE evil (id int)")',
    'con.execute("CALL sp_danger(1)")',
    'con.execute("TRUNCATE TABLE logs")',
    'con.execute("SELECT 1; CALL sp_drop(1)")',
]


@pytest.mark.parametrize("code", BLOCKED_WRITE_SQL)
def test_write_sql_at_executor_is_blocked(code):
    assert _is_blocked(code), f"write SQL wrongly allowed: {code!r}"


# --- Sandbox-escape checks must remain intact (bounded blacklist) ----------
BLOCKED_ESCAPES = [
    "import os",
    "from subprocess import run",
    "eval('1+1')",
    "open('/etc/passwd')",
    "x = ().__class__.__bases__",
]


@pytest.mark.parametrize("code", BLOCKED_ESCAPES)
def test_sandbox_escapes_still_blocked(code):
    assert _is_blocked(code), f"sandbox escape wrongly allowed: {code!r}"
