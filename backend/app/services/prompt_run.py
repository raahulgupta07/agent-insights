"""Parameter-template rendering for saved Prompts (feature PARAM_TEMPLATES).

Pure, dependency-free substitution engine so it stays unit-testable and can be
exercised directly with `python3 -m app.services.prompt_run` from backend/.

A saved Prompt's `text` may contain `{{name}}` placeholders; `parameters` describes
each placeholder (see schemas.prompt_schema.PromptParameter). `render_prompt_template`
fills the placeholders from caller-supplied `values`, falling back to each param's
`default`, and raises for any missing REQUIRED param. Unknown `{{...}}` placeholders
(not declared in the spec) are left untouched.
"""
from __future__ import annotations

import re
from typing import Any

# {{ name }} — optional inner whitespace; name = word chars / dot / dash.
_PLACEHOLDER_RE = re.compile(r"\{\{\s*([\w.\-]+)\s*\}\}")


def render_prompt_template(content: str, params_spec: list[dict], values: dict) -> str:
    """Substitute `{{name}}` placeholders in `content`.

    - Each declared param is replaced with its provided value, else its `default`.
    - A REQUIRED param with no provided value AND no default raises ValueError
      (listing every such missing param).
    - Placeholders whose name is not declared in `params_spec` are left intact.
    """
    content = content or ""
    params_spec = params_spec or []
    values = values or {}

    # Resolve the effective value for every declared param.
    resolved: dict[str, str] = {}
    missing_required: list[str] = []
    for spec in params_spec:
        name = (spec or {}).get("name")
        if not name:
            continue
        required = bool((spec or {}).get("required", False))
        provided = values.get(name)
        if provided is not None and provided != "":
            resolved[name] = str(provided)
            continue
        default = (spec or {}).get("default")
        if default is not None and default != "":
            resolved[name] = str(default)
            continue
        if required:
            missing_required.append(name)
        else:
            # Known, optional, unvalued -> substitute empty string.
            resolved[name] = ""

    if missing_required:
        raise ValueError(
            "Missing required parameter(s): " + ", ".join(sorted(set(missing_required)))
        )

    def _sub(match: "re.Match[str]") -> str:
        key = match.group(1)
        if key in resolved:
            return resolved[key]
        return match.group(0)  # unknown placeholder -> leave untouched

    return _PLACEHOLDER_RE.sub(_sub, content)


if __name__ == "__main__":
    # Self-test: `python3 -m app.services.prompt_run` from backend/ (exit 0 = pass).
    # 1. basic substitution
    assert render_prompt_template(
        "Hello {{name}}", [{"name": "name"}], {"name": "World"}
    ) == "Hello World"

    # 2. default fill when value missing and not required
    assert render_prompt_template(
        "Region: {{region}}", [{"name": "region", "default": "APAC"}], {}
    ) == "Region: APAC"

    # 3. missing required raises ValueError
    try:
        render_prompt_template("{{x}}", [{"name": "x", "required": True}], {})
        raise AssertionError("expected ValueError for missing required param")
    except ValueError as e:
        assert "x" in str(e)

    # 4. unknown placeholder left intact
    assert render_prompt_template(
        "{{known}} {{unknown}}", [{"name": "known"}], {"known": "A"}
    ) == "A {{unknown}}"

    # 5. whitespace inside braces + provided value overrides default
    assert render_prompt_template(
        "{{ q }}", [{"name": "q", "default": "d"}], {"q": "live"}
    ) == "live"

    # 6. numeric value coerced to string
    assert render_prompt_template(
        "top {{n}}", [{"name": "n", "type": "number"}], {"n": 5}
    ) == "top 5"

    print("prompt_run self-test: all assertions passed")
