"""Unit tests for app.ai.skills.invocation (pure, stdlib + pytest only)."""

import importlib.util
import os
import sys

# Insert backend root on sys.path (no conftest in this run).
_BACKEND_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(__file__), os.pardir, os.pardir)
)
if _BACKEND_ROOT not in sys.path:
    sys.path.insert(0, _BACKEND_ROOT)

# Load the module directly by file path so the test does not depend on every
# intermediate package having an __init__.py (the module itself is pure).
_MODULE_PATH = os.path.join(
    _BACKEND_ROOT, "app", "ai", "skills", "invocation.py"
)
_spec = importlib.util.spec_from_file_location("invocation_under_test", _MODULE_PATH)
invocation = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(invocation)

parse_slash_command = invocation.parse_slash_command
substitute_arguments = invocation.substitute_arguments


# --- parse_slash_command: normal cases --------------------------------------

def test_parse_normal_command_with_args():
    assert parse_slash_command("/foo bar baz") == ("foo", "bar baz")


def test_parse_command_no_args():
    assert parse_slash_command("/foo") == ("foo", "")


def test_parse_leading_spaces():
    assert parse_slash_command("  /foo x") == ("foo", "x")


def test_parse_hyphenated_name():
    assert parse_slash_command("/my-skill a") == ("my-skill", "a")


def test_parse_underscore_and_digits_name():
    assert parse_slash_command("/foo_2bar do it") == ("foo_2bar", "do it")


def test_parse_args_stripped():
    # extra whitespace around the args run is collapsed/stripped
    assert parse_slash_command("/foo    bar   ") == ("foo", "bar")


def test_parse_multiline_args_dotall():
    # DOTALL: the argument tail spans newlines and is preserved (then stripped).
    result = parse_slash_command("/foo line1\nline2\nline3")
    assert result == ("foo", "line1\nline2\nline3")


# --- parse_slash_command: rejection cases -----------------------------------

def test_parse_not_a_slash():
    assert parse_slash_command("hello") is None


def test_parse_empty_string():
    assert parse_slash_command("") is None


def test_parse_none():
    assert parse_slash_command(None) is None


def test_parse_bare_slash():
    assert parse_slash_command("/") is None


def test_parse_slash_space_foo():
    # a space right after the slash -> no name char -> None
    assert parse_slash_command("/ foo") is None


def test_parse_non_str_int():
    assert parse_slash_command(123) is None


def test_parse_non_str_list():
    assert parse_slash_command(["/foo"]) is None


def test_parse_only_whitespace():
    assert parse_slash_command("   ") is None


# --- substitute_arguments: ARGUMENTS / $0 -----------------------------------

def test_sub_arguments_full_replace():
    assert substitute_arguments("run: $ARGUMENTS", "a b c") == "run: a b c"


def test_sub_dollar_zero_equals_full():
    assert substitute_arguments("all=$0", "a b c") == "all=a b c"


def test_sub_arguments_and_zero_agree():
    body = "$ARGUMENTS | $0"
    assert substitute_arguments(body, "x y") == "x y | x y"


# --- substitute_arguments: positional ---------------------------------------

def test_sub_positional_first_second():
    assert substitute_arguments("$1 and $2", "alpha beta") == "alpha and beta"


def test_sub_positional_out_of_range():
    # two args, $3 is out of range -> empty string
    assert substitute_arguments("[$3]", "one two") == "[]"


def test_sub_mixed_body():
    assert substitute_arguments("do $1 then $ARGUMENTS", "x y") == "do x then x y"


def test_sub_no_placeholders_unchanged():
    body = "nothing to substitute here"
    assert substitute_arguments(body, "a b c") == body


def test_sub_empty_args_all_blank():
    assert substitute_arguments("$ARGUMENTS|$0|$1|$2", "") == "|||"


def test_sub_tenth_positional():
    # build 11 args so $10 picks the tenth, distinct from $1 + literal '0'
    args = "a1 a2 a3 a4 a5 a6 a7 a8 a9 a10 a11"
    assert substitute_arguments("got $10", args) == "got a10"
    # sanity: $1 is still the first positional
    assert substitute_arguments("got $1", args) == "got a1"


def test_sub_adjacent_text_word_boundary():
    # the regex consumes only the token "$1", so surrounding chars stay put
    assert substitute_arguments("x$1y", "VAL") == "xVALy"


def test_sub_adjacent_arguments_token():
    assert substitute_arguments("[$ARGUMENTS]", "a b") == "[a b]"


# --- substitute_arguments: bad / edge inputs --------------------------------

def test_sub_body_none_returns_empty():
    assert substitute_arguments(None, "a b") == ""


def test_sub_body_non_str_unchanged():
    assert substitute_arguments(123, "a b") == 123


def test_sub_args_str_none_treated_as_empty():
    # args_str None -> treated as empty; placeholders blank out
    assert substitute_arguments("$ARGUMENTS|$1", None) == "|"


def test_sub_args_str_whitespace_only():
    assert substitute_arguments("[$ARGUMENTS]", "   ") == "[]"


def test_sub_multiple_same_placeholder():
    assert substitute_arguments("$1 $1 $1", "z") == "z z z"
