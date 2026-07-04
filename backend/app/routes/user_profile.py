import os
import hashlib
from io import BytesIO

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from fastapi.responses import FileResponse
from typing import Optional
from pydantic import BaseModel
from PIL import Image

from app.models.user import User
from app.core.auth import current_user

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession
from app.dependencies import get_async_db
from app.schemas.user_profile_schema import UserProfileSchema
from app.schemas.organization_schema import OrganizationAndRoleSchema
from app.services.organization_service import OrganizationService

router = APIRouter(tags=["users"])
organization_service = OrganizationService()

@router.get("/users/whoami", response_model=UserProfileSchema)
async def get_user_profile(current_user: User = Depends(current_user), db: AsyncSession = Depends(get_async_db)):
    # Fetch organizations for the current user
    organizations = await organization_service.get_user_organizations(db, current_user)

    # Convert current_user to a dictionary
    user_data = current_user.dict() if hasattr(current_user, 'dict') else vars(current_user)

    # Return the user profile with formatted organizations
    return UserProfileSchema(
        **user_data,
        organizations=organizations
    )


# ---------------------------------------------------------------------------
# User avatar upload (HYBRID_USER_AVATAR gates only the FE affordance; the
# serve route + column exist unconditionally so an already-uploaded avatar keeps
# rendering even if the flag is later turned off). Storage reuses the fork's
# `uploads/` mechanism (the ca_uploads volume; same relative dir as
# FileService.upload_file's `uploads/files/`).
# ---------------------------------------------------------------------------

_AVATAR_MAX_BYTES = 5 * 1024 * 1024  # 5 MB upload cap
_AVATAR_DIR = "uploads/avatars"


class UserAvatarSchema(BaseModel):
    image_url: Optional[str] = None


@router.post("/users/me/avatar", response_model=UserAvatarSchema)
async def upload_my_avatar(
    avatar: UploadFile = File(...),
    current_user: User = Depends(current_user),
    db: AsyncSession = Depends(get_async_db),
):
    """Upload the current user's profile image. The image is normalized to a
    square 256x256 PNG and served publicly via /api/users/avatar/{key}."""
    raw = await avatar.read()
    if not raw:
        raise HTTPException(status_code=400, detail="Empty file")
    if len(raw) > _AVATAR_MAX_BYTES:
        raise HTTPException(status_code=400, detail="Image is too large (max 5 MB)")

    try:
        image = Image.open(BytesIO(raw))
        image.load()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid image file")

    image = image.convert("RGBA")

    # Center-crop to a square, then resize to 256x256 for a consistent avatar.
    width, height = image.size
    side = min(width, height)
    left = (width - side) // 2
    top = (height - side) // 2
    image = image.crop((left, top, left + side, top + side))
    image = image.resize((256, 256), Image.Resampling.LANCZOS)

    os.makedirs(_AVATAR_DIR, exist_ok=True)

    digest = hashlib.sha256(raw).hexdigest()[:16]
    filename = f"{current_user.id}-{digest}.png"
    file_path = os.path.join(_AVATAR_DIR, filename)

    buf = BytesIO()
    image.save(buf, format="PNG")
    with open(file_path, "wb") as f:
        f.write(buf.getvalue())

    image_url = f"/api/users/avatar/{filename}"
    # current_user is bound to the auth/user-manager session, not `db`, so we
    # update via a statement rather than mutating the ORM object (avoids touching
    # a cross-session object; mirrors _update_last_seen in app/core/auth.py).
    await db.execute(
        update(User).where(User.id == str(current_user.id)).values(image_url=image_url)
    )
    await db.commit()
    return UserAvatarSchema(image_url=image_url)


@router.delete("/users/me/avatar", response_model=UserAvatarSchema)
async def delete_my_avatar(
    current_user: User = Depends(current_user),
    db: AsyncSession = Depends(get_async_db),
):
    """Remove the current user's avatar, reverting to the initial placeholder.
    Idempotent: clearing an already-NULL column and a missing file are no-ops."""
    # Best-effort delete of the stored file (from the current column value).
    current = getattr(current_user, "image_url", None)
    if current:
        name = current.rsplit("/", 1)[-1]
        if name and "/" not in name and "\\" not in name and ".." not in name:
            try:
                os.remove(os.path.join(_AVATAR_DIR, name))
            except OSError:
                pass  # already gone / never written — fine
    await db.execute(
        update(User).where(User.id == str(current_user.id)).values(image_url=None)
    )
    await db.commit()
    return UserAvatarSchema(image_url=None)


@router.get("/users/avatar/{key}")
async def serve_avatar(key: str):
    """Public serve of an uploaded avatar PNG. `key` must be a plain filename —
    any path separator or traversal token is rejected so it can never escape the
    avatars directory."""
    if not key or "/" in key or "\\" in key or ".." in key or key.startswith("."):
        raise HTTPException(status_code=400, detail="Invalid avatar key")
    file_path = os.path.join(_AVATAR_DIR, key)
    if not os.path.isfile(file_path):
        raise HTTPException(status_code=404, detail="Avatar not found")
    return FileResponse(file_path, media_type="image/png")
