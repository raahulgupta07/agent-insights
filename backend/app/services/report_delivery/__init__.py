"""Universal report delivery — render a report/dashboard/workflow/artifact into
an email body + inline images + attachments, then send via the per-agent SMTP
resolver.

P0 scaffold: only the CONTRACT lives here (frozen so P3/P4/P5 renderers can be
authored in parallel without colliding). The Mode-A renderer + the rewire of
``notification_service.send_scheduled_prompt_results`` land in P1.

Every mode renderer is a callable ``render(ctx) -> DeliveryParts`` registered
under a mode key. ``classify(ctx)`` picks the key. The email assembler wraps the
returned parts in the shared template skeleton. Nothing here is wired into a send
path yet — importing this module has no runtime effect.
"""
from .contract import (
    DeliveryContext,
    DeliveryParts,
    InlineImage,
    Attachment,
    register_renderer,
    get_renderer,
    list_modes,
    classify,
)

__all__ = [
    "DeliveryContext",
    "DeliveryParts",
    "InlineImage",
    "Attachment",
    "register_renderer",
    "get_renderer",
    "list_modes",
    "classify",
]
