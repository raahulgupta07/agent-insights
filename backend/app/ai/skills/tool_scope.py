"""Claude-Code "allowed-tools" per-skill catalog narrowing.

Pure, dependency-free, never-raises helpers that mirror Claude Code semantics:
when a skill is active it may declare an ``allowed_tools`` allow-list (and an
optional ``disallowed_tools`` deny-list) that narrows the tool catalog the
planner sees. A small set of meta-tools always survive narrowing so the agent
can always load another skill, ask for clarification, or finish.
"""

NEVER_DROP = {"load_skill", "read_skill_file", "clarify", "done"}  # always survive narrowing


def narrow_catalog(catalog, allowed_tools, disallowed_tools=None, never_drop=None):
    """Narrow a planner tool catalog to a skill's allowed-tools, mirroring
    Claude Code semantics.

    catalog: list of tool dicts (each has a "name" key) -- the full catalog the
             planner would otherwise see.
    allowed_tools: list[str] of tool names the active skill permits. EMPTY or
             None => NO narrowing (return catalog unchanged minus disallowed) --
             this matches Claude Code: allowed-tools restricts the prompt-free
             set but an empty list means "don't narrow".
    disallowed_tools: list[str] removed from the catalog even if allowed.
    never_drop: set of tool names that always survive (default NEVER_DROP) -- the
             agent must keep meta-tools (load_skill so it can load another skill,
             clarify, done) regardless of the skill's allow-list.

    Returns a NEW filtered list (does not mutate input). Order preserved.
    Logic:
      - start from catalog
      - if allowed_tools non-empty: keep a tool iff name in allowed_tools OR
        name in never_drop
      - then drop any tool whose name in disallowed_tools UNLESS in never_drop
      - dedupe defensively by name, preserve first occurrence/order
    Tolerant: items missing a "name" key are dropped quietly. allowed/disallowed
    entries are matched case-sensitively by exact tool name. NEVER raises -- on any
    unexpected error return the original catalog list unchanged.
    """
    try:
        if not isinstance(catalog, (list, tuple)):
            return catalog

        if never_drop is None:
            never_drop = NEVER_DROP
        never_set = set(never_drop) if never_drop else set()

        allow_set = set(allowed_tools) if allowed_tools else set()
        deny_set = set(disallowed_tools) if disallowed_tools else set()

        result = []
        seen = set()
        for tool in catalog:
            try:
                name = tool.get("name")
            except AttributeError:
                # not a mapping -> no usable name, drop quietly
                continue
            if name is None:
                continue

            is_meta = name in never_set

            # allow-list narrowing (only when non-empty)
            if allow_set and not is_meta and name not in allow_set:
                continue

            # deny-list removal (meta-tools survive)
            if name in deny_set and not is_meta:
                continue

            # defensive dedupe by name, first occurrence wins
            if name in seen:
                continue
            seen.add(name)
            result.append(tool)

        return result
    except Exception:
        return catalog


def active_skill_tools(active_skill):
    """Pull (allowed_tools, disallowed_tools) lists out of a runtime active_skill
    dict {"name","allowed_tools","disallowed_tools"}; ([],[]) when None/missing.
    """
    try:
        if not active_skill:
            return [], []
        allowed = active_skill.get("allowed_tools") or []
        disallowed = active_skill.get("disallowed_tools") or []
        if not isinstance(allowed, (list, tuple)):
            allowed = []
        if not isinstance(disallowed, (list, tuple)):
            disallowed = []
        return list(allowed), list(disallowed)
    except Exception:
        return [], []
