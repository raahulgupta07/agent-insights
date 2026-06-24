"""Unit tests for app.ai.skills.frontmatter (stdlib-only, no conftest deps)."""

import os
import sys

import pytest

# Make the backend root importable without relying on conftest.
_BACKEND_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..")
)
if _BACKEND_ROOT not in sys.path:
    sys.path.insert(0, _BACKEND_ROOT)

from app.ai.skills.frontmatter import (  # noqa: E402
    build_skill_md,
    extract_skill_fields,
    parse_frontmatter,
)


def test_parse_basic_frontmatter():
    md = "---\nname: foo\ndescription: bar\n---\n\nHello body\n"
    fm, body = parse_frontmatter(md)
    assert fm == {"name": "foo", "description": "bar"}
    assert body == "Hello body\n"


def test_no_frontmatter_passthrough():
    md = "# Just markdown\n\nNo frontmatter here.\n"
    fm, body = parse_frontmatter(md)
    assert fm == {}
    assert body == md


def test_no_closing_delimiter_passthrough():
    md = "---\nname: foo\nno closing delimiter\n"
    fm, body = parse_frontmatter(md)
    assert fm == {}
    assert body == md


def test_malformed_yaml_safe_defaults():
    # Unbalanced brackets / bad mapping -> yaml error -> safe defaults.
    md = "---\nname: [unclosed\n---\nbody\n"
    fm, body = parse_frontmatter(md)
    assert fm == {}
    assert body == md


def test_non_dict_yaml_passthrough():
    # A YAML list (not a mapping) is not valid frontmatter.
    md = "---\n- a\n- b\n---\nbody\n"
    fm, body = parse_frontmatter(md)
    assert fm == {}
    assert body == md


def test_build_skill_md_round_trip():
    fm_in = {"name": "foo", "description": "does a thing"}
    body_in = "## Steps\n\nDo the thing.\n"
    md = build_skill_md(fm_in, body_in)
    assert md.startswith("---\n")
    fm_out, body_out = parse_frontmatter(md)
    assert fm_out == fm_in
    assert body_out == body_in


def test_build_skill_md_preserves_key_order():
    md = build_skill_md({"name": "z", "description": "a", "license": "MIT"}, "b")
    # sort_keys=False -> declared order retained.
    assert md.index("name:") < md.index("description:") < md.index("license:")


def test_build_skill_md_empty_frontmatter_returns_body():
    body = "just the body\n"
    assert build_skill_md({}, body) == body
    assert build_skill_md(None, body) == body


def test_extract_hyphen_aliases_normalize():
    md = (
        "---\n"
        "name: foo\n"
        "allowed-tools: Read Bash create_data\n"
        "disallowed-tools: rm\n"
        "disable-model-invocation: true\n"
        "user-invocable: false\n"
        "---\n"
        "body\n"
    )
    f = extract_skill_fields(md)
    assert f["name"] == "foo"
    assert f["allowed_tools"] == ["Read", "Bash", "create_data"]
    assert f["disallowed_tools"] == ["rm"]
    assert f["disable_model_invocation"] is True
    assert f["user_invocable"] is False


def test_extract_underscore_keys_also_work():
    md = (
        "---\n"
        "allowed_tools: Read Write\n"
        "disable_model_invocation: false\n"
        "---\n"
        "x\n"
    )
    f = extract_skill_fields(md)
    assert f["allowed_tools"] == ["Read", "Write"]
    assert f["disable_model_invocation"] is False


def test_allowed_tools_as_space_string():
    md = "---\nallowed-tools: Read Bash create_data\n---\nbody\n"
    f = extract_skill_fields(md)
    assert f["allowed_tools"] == ["Read", "Bash", "create_data"]


def test_allowed_tools_as_yaml_list():
    md = "---\nallowed-tools:\n  - Read\n  - Bash\n  - create_data\n---\nbody\n"
    f = extract_skill_fields(md)
    assert f["allowed_tools"] == ["Read", "Bash", "create_data"]


def test_bool_coercion_truthy_strings():
    for val in ("true", "TRUE", "yes", "Yes", "1", "on", "ON"):
        md = "---\ndisable-model-invocation: {}\n---\nb\n".format(val)
        f = extract_skill_fields(md)
        assert f["disable_model_invocation"] is True, val


def test_bool_coercion_falsy_strings():
    for val in ("false", "no", "0", "off", "nope"):
        md = "---\ndisable-model-invocation: {}\n---\nb\n".format(val)
        f = extract_skill_fields(md)
        assert f["disable_model_invocation"] is False, val


def test_defaults_when_absent():
    f = extract_skill_fields("---\nname: foo\n---\nbody\n")
    assert f["name"] == "foo"
    assert f["description"] is None
    assert f["allowed_tools"] == []
    assert f["disallowed_tools"] == []
    assert f["disable_model_invocation"] is False
    assert f["user_invocable"] is True
    assert f["metadata"] == {}
    assert f["license"] is None
    assert f["body"] == "body\n"


def test_metadata_and_license_extraction():
    md = (
        "---\n"
        "name: foo\n"
        "license: Apache-2.0\n"
        "metadata:\n"
        "  author: rahul\n"
        "  version: 2\n"
        "---\n"
        "body\n"
    )
    f = extract_skill_fields(md)
    assert f["license"] == "Apache-2.0"
    assert f["metadata"] == {"author": "rahul", "version": 2}


def test_metadata_non_dict_falls_back_to_empty():
    md = "---\nmetadata: not-a-dict\n---\nbody\n"
    f = extract_skill_fields(md)
    assert f["metadata"] == {}


def test_extract_no_frontmatter_returns_defaults_with_body():
    md = "# plain\n\nno frontmatter\n"
    f = extract_skill_fields(md)
    assert f["name"] is None
    assert f["body"] == md
    assert f["allowed_tools"] == []
    assert f["user_invocable"] is True


def test_extract_malformed_safe_defaults_body_is_original():
    md = "---\nname: [unclosed\n---\nbody\n"
    f = extract_skill_fields(md)
    assert f["name"] is None
    assert f["body"] == md  # parse_frontmatter returned original on error


def test_extract_non_string_input_never_raises():
    f = extract_skill_fields(None)  # type: ignore[arg-type]
    assert f["name"] is None
    assert f["body"] == ""
    assert f["allowed_tools"] == []


def test_build_then_extract_round_trip_full():
    fm_in = {
        "name": "deploy",
        "description": "deploy the app",
        "allowed-tools": "Read Bash",
        "license": "MIT",
        "metadata": {"team": "infra"},
    }
    body_in = "Run the deploy.\n"
    md = build_skill_md(fm_in, body_in)
    f = extract_skill_fields(md)
    assert f["name"] == "deploy"
    assert f["description"] == "deploy the app"
    assert f["allowed_tools"] == ["Read", "Bash"]
    assert f["license"] == "MIT"
    assert f["metadata"] == {"team": "infra"}
    assert f["body"] == body_in


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
