"""Mode D — artifact: email a generated deck (PPTX) or report doc (PDF) as an
inline page-1 preview PNG + the file attached, plus a short title/intro.

The accurate, shippable thing for a deck/report report is the *file itself*, not
its raw chat prose. So this renderer resolves the LATEST file-bearing
``Artifact`` for the report, renders its first page to a small PNG (PDF directly
via ``pdftoppm``; PPTX first converted to PDF via headless LibreOffice
``soffice``), inlines that PNG, attaches the original file, and frames it with a
one-paragraph intro lifted from the sanitized agent narrative.

NEVER raises into the send path:
  * no artifact found        -> minimal body, no inline, no attachment
  * preview generation fails -> still attach the file, just drop the inline image

Ownership note: this is the ONLY file Phase P4 adds. It imports the frozen
contract + the reusable ``template``/``extract`` helpers and registers itself as
the "artifact" renderer at import time. It does NOT touch render_service.py
(owned by the parallel P3 agent) or any other module.
"""
from __future__ import annotations

import asyncio
import base64
import logging
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Optional

from app.services.report_delivery.contract import (
    Attachment,
    DeliveryContext,
    DeliveryParts,
    InlineImage,
    register_renderer,
)
from app.services.report_delivery import extract, template

logger = logging.getLogger(__name__)

# uploads/ lives at <repo>/backend/uploads — this file is
# backend/app/services/report_delivery/renderers/artifact.py, so go up 5.
_UPLOADS = Path(__file__).resolve().parents[4] / "uploads"

# MIME maps for the attachment + the preview rasterizer.
_PPTX_MIME = ("application", "vnd.openxmlformats-officedocument.presentationml.presentation")
_PDF_MIME = ("application", "pdf")

# A page-1 PNG of a slide/page is small; cap the soffice conversion which can be
# slow (cold JVM ~5-10s). Fail-soft past this — the file still attaches.
_SOFFICE_TIMEOUT = 60
_PDFTOPPM_TIMEOUT = 30


# --------------------------------------------------------------------------- #
# artifact resolution
# --------------------------------------------------------------------------- #


class _ResolvedArtifact:
    """Plain holder: the artifact's file bytes + presentation metadata."""

    __slots__ = ("file_bytes", "filename", "ext", "kind", "screenshot_b64", "preview_png")

    def __init__(self) -> None:
        self.file_bytes: Optional[bytes] = None
        self.filename: str = "artifact"
        self.ext: str = ""            # "pdf" | "pptx"
        self.kind: str = "artifact"   # human label for the intro ("deck"/"report")
        self.screenshot_b64: Optional[str] = None   # ready-made preview, if any
        self.preview_png: Optional[bytes] = None     # pre-rendered slide-01 PNG, if any


def _safe_slug(name: str) -> str:
    base = "".join(c if (c.isalnum() or c in " -_") else "_" for c in (name or "")).strip()
    return (base or "artifact")[:80]


async def _resolve_latest_artifact(report_id: str, title: str) -> Optional[_ResolvedArtifact]:
    """Newest non-failed file-bearing Artifact for the report → bytes + meta.

    Slides ('slides' mode) resolve to a PPTX; everything else falls back to the
    derived report PDF if one exists on disk. Read-only; returns None when there
    is no artifact (or no file we can attach) so the caller can fail soft.
    """
    try:
        from sqlalchemy import select, desc
        from app.dependencies import async_session_maker
        from app.models.artifact import Artifact
    except Exception as e:  # noqa: BLE001
        logger.warning("artifact renderer: model import failed: %s", e)
        return None

    try:
        async with async_session_maker() as db:
            rows = (
                await db.execute(
                    select(Artifact)
                    .where(Artifact.report_id == report_id)
                    .order_by(desc(Artifact.created_at))
                    .limit(12)
                )
            ).scalars().all()
            if not rows:
                return None

            # Prefer the newest artifact we can actually turn into a file. Walk
            # newest→older so a half-built latest doesn't shadow a good one.
            for a in rows:
                if (getattr(a, "status", "") or "").lower() == "failed":
                    continue
                res = _file_for_artifact(a, title)
                if res is not None:
                    return res
    except Exception as e:  # noqa: BLE001
        logger.warning("artifact renderer: artifact lookup failed: %s", e)
        return None
    return None


def _file_for_artifact(a, title: str) -> Optional[_ResolvedArtifact]:
    """Pick the on-disk file (pptx/pdf) for one Artifact row; capture any
    ready-made preview the pipeline produced earlier."""
    res = _ResolvedArtifact()
    aid = str(a.id)
    art_title = (getattr(a, "title", None) or title or "artifact").strip() or "artifact"
    slug = _safe_slug(art_title)
    mode = (getattr(a, "mode", "") or "").lower()

    # ready-made preview hints (used only if live rasterization fails) ---------
    res.screenshot_b64 = getattr(a, "screenshot_base64", None)
    prev = _UPLOADS / "pptx_previews" / aid / "slide-01.png"
    if prev.is_file():
        try:
            res.preview_png = prev.read_bytes()
        except OSError:
            res.preview_png = None

    # 1) slides → PPTX (stored absolute path, else deterministic uploads path)
    pptx_path: Optional[Path] = None
    raw = getattr(a, "pptx_path", None)
    if raw and ".." not in str(raw):
        p = Path(str(raw))
        if not p.is_absolute():
            p = _UPLOADS / "pptx" / p.name
        if p.is_file():
            pptx_path = p
    if pptx_path is None:
        cand = _UPLOADS / "pptx" / f"{aid}.pptx"
        if cand.is_file():
            pptx_path = cand
    if pptx_path is not None:
        try:
            res.file_bytes = pptx_path.read_bytes()
            res.filename = f"{slug}.pptx"
            res.ext = "pptx"
            res.kind = "deck"
            return res
        except OSError as e:
            logger.warning("artifact renderer: pptx read failed (%s): %s", pptx_path, e)

    # 2) derived report PDF (deterministic by artifact id)
    pdf = _UPLOADS / "pdfs" / f"{aid}.pdf"
    if pdf.is_file():
        try:
            res.file_bytes = pdf.read_bytes()
            res.filename = f"{slug}.pdf"
            res.ext = "pdf"
            res.kind = "report"
            return res
        except OSError as e:
            logger.warning("artifact renderer: pdf read failed (%s): %s", pdf, e)

    # No attachable file for this row (mode without an exported file yet).
    return None


# --------------------------------------------------------------------------- #
# page-1 preview rasterization (subprocess; fail-soft)
# --------------------------------------------------------------------------- #


def _which(*names: str) -> Optional[str]:
    for n in names:
        path = shutil.which(n)
        if path:
            return path
    return None


def _pdf_to_png(pdf_path: Path, workdir: Path) -> Optional[bytes]:
    """First page of a PDF → PNG bytes via poppler ``pdftoppm`` (or pdftocairo)."""
    tool = _which("pdftoppm")
    if tool:
        prefix = workdir / "page"
        cmd = [tool, "-png", "-f", "1", "-l", "1", "-r", "110", str(pdf_path), str(prefix)]
    else:
        tool = _which("pdftocairo")
        if not tool:
            logger.warning("artifact renderer: no pdftoppm/pdftocairo on PATH")
            return None
        prefix = workdir / "page"
        cmd = [tool, "-png", "-singlefile", "-f", "1", "-l", "1", "-r", "110",
               str(pdf_path), str(prefix)]
    try:
        subprocess.run(
            cmd, cwd=str(workdir), timeout=_PDFTOPPM_TIMEOUT,
            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, check=True,
        )
    except Exception as e:  # noqa: BLE001 — timeout / nonzero / missing tool
        logger.warning("artifact renderer: pdf->png failed: %s", e)
        return None
    pngs = sorted(workdir.glob("page*.png"))
    if not pngs:
        return None
    try:
        return pngs[0].read_bytes()
    except OSError:
        return None


def _pptx_to_png(pptx_path: Path, workdir: Path) -> Optional[bytes]:
    """First slide of a PPTX → PNG: ``soffice`` converts to PDF, then pdftoppm."""
    soffice = _which("soffice", "libreoffice")
    if not soffice:
        logger.warning("artifact renderer: no soffice/libreoffice on PATH")
        return None
    profile = workdir / "lo_profile"
    cmd = [
        soffice, "--headless", "--norestore", "--nologo", "--nofirststartwizard",
        f"-env:UserInstallation=file://{profile}",
        "--convert-to", "pdf", "--outdir", str(workdir), str(pptx_path),
    ]
    try:
        subprocess.run(
            cmd, cwd=str(workdir), timeout=_SOFFICE_TIMEOUT,
            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, check=True,
        )
    except Exception as e:  # noqa: BLE001 — soffice is slow/flaky; never fatal
        logger.warning("artifact renderer: pptx->pdf (soffice) failed: %s", e)
        return None
    pdfs = sorted(workdir.glob("*.pdf"))
    if not pdfs:
        return None
    return _pdf_to_png(pdfs[0], workdir)


def _build_preview_blocking(res: _ResolvedArtifact) -> Optional[bytes]:
    """Synchronous preview build (runs in a thread). Returns PNG bytes or None.

    Tries live rasterization of the real file first (most faithful), then falls
    back to any pre-rendered slide PNG / stored screenshot the app already made.
    """
    if res.file_bytes:
        workdir = Path(tempfile.mkdtemp(prefix="artifact_preview_"))
        try:
            src = workdir / f"input.{res.ext or 'bin'}"
            src.write_bytes(res.file_bytes)
            if res.ext == "pdf":
                png = _pdf_to_png(src, workdir)
            elif res.ext == "pptx":
                png = _pptx_to_png(src, workdir)
            else:
                png = None
            if png:
                return png
        except Exception as e:  # noqa: BLE001
            logger.warning("artifact renderer: preview build error: %s", e)
        finally:
            shutil.rmtree(workdir, ignore_errors=True)

    # fallbacks: pre-rendered slide PNG, then stored base64 screenshot
    if res.preview_png:
        return res.preview_png
    if res.screenshot_b64:
        try:
            b64 = res.screenshot_b64
            if "," in b64 and b64.strip().lower().startswith("data:"):
                b64 = b64.split(",", 1)[1]
            return base64.b64decode(b64)
        except Exception:  # noqa: BLE001
            return None
    return None


async def _build_preview(res: _ResolvedArtifact) -> Optional[bytes]:
    """Off-load the blocking subprocess pipeline to a worker thread."""
    try:
        return await asyncio.to_thread(_build_preview_blocking, res)
    except Exception as e:  # noqa: BLE001
        logger.warning("artifact renderer: preview thread failed: %s", e)
        return None


# --------------------------------------------------------------------------- #
# renderer
# --------------------------------------------------------------------------- #


_FOOTER = "Generated automatically and delivered via this agent's email."


async def render(ctx: DeliveryContext) -> DeliveryParts:
    """Render the artifact email parts. Never raises."""
    res: Optional[_ResolvedArtifact] = None
    try:
        res = await _resolve_latest_artifact(ctx.report_id, ctx.title)
    except Exception as e:  # noqa: BLE001 — resolution must never break the send
        logger.warning("artifact renderer: resolve failed: %s", e)
        res = None

    # 1) no artifact -> minimal body, nothing attached -----------------------
    if res is None or not res.file_bytes:
        body = template.skeleton(
            title=ctx.title or "Report",
            meta="Automated artifact · agent report",
            inner_html="<p style='font-size:13.5px;color:#555'>No artifact available.</p>",
            report_url=ctx.report_url,
            footer=_FOOTER,
        )
        return DeliveryParts(body_html=body, subject=ctx.title or "Report")

    # 2) intro from the sanitized agent narrative ----------------------------
    intro = ""
    try:
        narrative = extract.sanitize_chat_content(await extract.latest_narrative(ctx.report_id))
        intro, _ = extract.split_intro_and_insights(narrative)
    except Exception as e:  # noqa: BLE001
        logger.warning("artifact renderer: narrative extract failed: %s", e)
        intro = ""
    if not intro:
        intro = f"Your generated {res.kind} is attached."

    # 3) page-1 preview (fail-soft → drop inline, keep attachment) ------------
    png: Optional[bytes] = None
    try:
        png = await _build_preview(res)
    except Exception as e:  # noqa: BLE001
        logger.warning("artifact renderer: preview failed: %s", e)
        png = None

    # 4) assemble inner html --------------------------------------------------
    inner = f"<p style='font-size:13.5px;line-height:1.5;color:#222'>{intro}</p>"
    if png:
        inner += (
            "<img src=\"cid:preview\" "
            "style=\"max-width:560px;width:100%;border:1px solid #eee\">"
        )

    body = template.skeleton(
        title=ctx.title or res.filename,
        meta="Automated artifact · agent report",
        inner_html=inner,
        report_url=ctx.report_url,
        footer=_FOOTER,
    )

    maintype, subtype = _PDF_MIME if res.ext == "pdf" else (
        _PPTX_MIME if res.ext == "pptx" else ("application", "octet-stream")
    )

    return DeliveryParts(
        body_html=body,
        inline_images=[InlineImage(cid="preview", content=png, mime_subtype="png")] if png else [],
        attachments=[
            Attachment(
                filename=res.filename,
                content=res.file_bytes,
                mime_type=maintype,
                mime_subtype=subtype,
            )
        ],
        subject=ctx.title or res.filename,
    )


register_renderer("artifact", render)
