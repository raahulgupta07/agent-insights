from pydantic import BaseModel
from datetime import datetime
from typing import Any, Optional
from app.schemas.file_tag_schema import FileTagSchema
from app.schemas.sheet_schema_schema_ import SheetSchema

class FileBase(BaseModel):
    pass

class FileCreate(FileBase):
    pass

class FileSchema(FileBase):
    id: str
    filename: str
    content_type: str
    path: str
    created_at: datetime
    # Raw upload preview (no LLM) — sheet names / raw cells / shape, produced by
    # file_preview.generate_file_preview. Additive + optional so existing callers
    # are unaffected; lets the upload modal light up its sheet/column preview.
    preview: Optional[Any] = None

    class Config:
        from_attributes = True


class FileSchemaWithCompletionId(FileSchema):
    """File schema that includes completion_id from the report_file_association."""
    completion_id: str | None = None
    # True when the file is attached to the report only because it was
    # auto-snapshotted from one of the report's data sources. The chat
    # prompt box uses this to hide inherited files from per-turn chips.
    from_data_source: bool = False


class FileSchemaWithMetadata(FileSchema):
    schemas: list[SheetSchema]
    tags: list[FileTagSchema]
