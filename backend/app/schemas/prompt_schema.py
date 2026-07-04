from pydantic import BaseModel
from typing import Optional, List, Any
from datetime import datetime
from uuid import UUID


class PromptParameter(BaseModel):
    name: str                            # placeholder key: {{name}}
    label: Optional[str] = None
    type: str = 'text'                   # 'text' | 'number' | 'enum' | 'date' | 'date_range'
    required: bool = False
    default: Optional[Any] = None
    options: Optional[List[str]] = None  # for type == 'enum'


class PromptBase(BaseModel):
    text: str


class PromptCreate(PromptBase):
    title: Optional[str] = None
    mode: str = 'chat'                   # 'chat' | 'deep' | 'training'
    model_id: Optional[str] = None
    mentions: Optional[List[dict]] = None
    parameters: Optional[List[PromptParameter]] = None
    scope: str = 'agent'                 # 'agent' | 'global' | 'private'
    is_starter: bool = False


class PromptUpdate(BaseModel):
    title: Optional[str] = None
    text: Optional[str] = None
    mode: Optional[str] = None
    model_id: Optional[str] = None
    mentions: Optional[List[dict]] = None
    parameters: Optional[List[PromptParameter]] = None
    scope: Optional[str] = None
    is_starter: Optional[bool] = None


class PromptResponse(PromptBase):
    id: UUID
    title: Optional[str] = None
    mode: Optional[str] = None
    model_id: Optional[str] = None
    mentions: Optional[List[dict]] = None
    parameters: Optional[List[PromptParameter]] = None
    scope: Optional[str] = None
    is_starter: Optional[bool] = None
    user_id: Optional[str] = None
    created_at: datetime

    class Config:
        orm_mode = True
