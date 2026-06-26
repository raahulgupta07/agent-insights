"""Mode renderers. Importing this package auto-imports every submodule so each
renderer self-registers via its module-level ``register_renderer(...)`` call.

This auto-discovery means a new renderer (dashboard / artifact / workflow) is
added by simply dropping ``renderers/<mode>.py`` — no edit to this file, so
parallel phases never collide here. A renderer that fails to import (missing
optional dep, etc.) is skipped fail-soft and just leaves its mode unregistered;
the assembler then falls back to "result".
"""
import importlib
import logging
import pkgutil

logger = logging.getLogger(__name__)

for _info in pkgutil.iter_modules(__path__):
    if _info.name.startswith("_"):
        continue
    try:
        importlib.import_module(f"{__name__}.{_info.name}")
    except Exception as e:  # noqa: BLE001 — one bad renderer must not break the rest
        logger.warning("report_delivery: renderer %r failed to load: %s", _info.name, e)
