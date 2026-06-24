"""Claude-Code-style slash-command parsing and ``$ARGUMENTS`` substitution.

Pure, dependency-free, never-raises helpers that mirror Claude Code semantics
for *skill invocation* (Phase S4):

* ``parse_slash_command`` recognizes a leading ``/skill-name optional args``
  line and splits it into ``(skill_name, args_str)``.
* ``substitute_arguments`` expands the Claude-Code argument placeholders inside
  a skill body -- ``$ARGUMENTS`` / ``$0`` (the full argument string) and the
  positional ``$1 .. $N`` tokens -- so a user-supplied argument string can be
  woven into the skill's instructions before it is handed to the planner.

Only the standard library (``re``) is used. Every public function is wrapped in
``try/except`` and returns a safe default on any error -- these helpers never
raise.
"""

from typing import Optional, Tuple

import re

__all__ = ["parse_slash_command", "substitute_arguments"]

# Matches a slash command at the very start of the text (after optional leading
# whitespace): a '/' immediately followed by one or more name characters, then
# (optionally) a run of whitespace and the remaining argument text. DOTALL lets
# the argument tail span multiple lines.
_SLASH_RE = re.compile(r"^\s*/([A-Za-z0-9_-]+)(?:\s+(.*))?$", re.DOTALL)

# Matches a single argument placeholder: '$ARGUMENTS' or '$<digits>'. The
# alternation tries the literal 'ARGUMENTS' token before the digit run so it is
# never mistaken for a stray positional, and a digit run is consumed greedily so
# that '$10' is the tenth positional (not '$1' followed by a literal '0').
_PLACEHOLDER_RE = re.compile(r"\$(ARGUMENTS|\d+)")


def parse_slash_command(text):
    # type: (object) -> Optional[Tuple[str, str]]
    """If ``text`` is a slash-command invocation, return ``(skill_name, args_str)``.

    A slash command is text whose FIRST non-whitespace character is ``/``, of
    the form ``/skill-name optional args here``. ``skill_name`` is the token
    immediately after ``/`` (letters, digits, ``_`` and ``-``; it stops at the
    first whitespace). ``args_str`` is everything after the first run of
    whitespace following the name, stripped (``""`` when there is nothing).

    Returns ``None`` when: ``text`` is ``None`` / empty / not a ``str``; it does
    not start with ``/``; or there is no name character after the ``/`` (a bare
    ``/`` or ``/ foo`` -- a space right after the slash -- yields ``None``).

    Never raises -> returns ``None`` on any error.
    """
    try:
        if not isinstance(text, str) or not text:
            return None

        match = _SLASH_RE.match(text)
        if match is None:
            return None

        name = match.group(1)
        if not name:
            return None

        args = match.group(2)
        args_str = args.strip() if args is not None else ""
        return name, args_str
    except Exception:
        return None


def substitute_arguments(body, args_str):
    # type: (object, object) -> object
    """Substitute Claude-Code argument placeholders inside ``body``.

    * ``$ARGUMENTS`` -> the full ``args_str`` (verbatim, stripped).
    * ``$0``         -> alias for the full ``args_str`` (same as ``$ARGUMENTS``).
    * ``$1 .. $N``   -> positional arguments (``args_str`` split on runs of
                        whitespace). An out-of-range positional -> empty string.

    Placeholders are matched as whole tokens (``$ARGUMENTS`` or ``$<digits>``)
    so ``$10`` resolves to the tenth positional argument and ``$ARGUMENTS`` is
    recognized ahead of the bare ``$N`` digits. Any unmatched/empty placeholder
    is replaced with ``""``. Adjacent text is preserved: ``"x$1y"`` becomes
    ``"x<arg1>y"`` because the regex consumes only the placeholder token.

    Returns the substituted string. If ``body`` is ``None`` -> ``""``; if
    ``body`` is not a ``str`` -> ``body`` unchanged. Never raises -> returns
    ``body`` (or ``""`` for ``None``) on any error.
    """
    try:
        if body is None:
            return ""
        if not isinstance(body, str):
            return body

        # Normalize the argument string and derive positional tokens.
        full = args_str.strip() if isinstance(args_str, str) else ""
        positionals = re.split(r"\s+", full) if full else []
        # Drop any empty fragments defensively (e.g. from odd inputs).
        positionals = [p for p in positionals if p != ""]

        def _repl(m):
            token = m.group(1)
            if token == "ARGUMENTS" or token == "0":
                return full
            try:
                idx = int(token)
            except (TypeError, ValueError):
                return ""
            if 1 <= idx <= len(positionals):
                return positionals[idx - 1]
            return ""

        return _PLACEHOLDER_RE.sub(_repl, body)
    except Exception:
        return body
