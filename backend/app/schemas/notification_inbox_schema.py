from typing import List, Optional
from datetime import datetime

from pydantic import BaseModel


class NotificationItem(BaseModel):
    id: str
    source: str
    type: str
    severity: str
    title: str
    body: Optional[str] = None
    link: Optional[str] = None
    is_read: bool = False
    read_at: Optional[datetime] = None
    created_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class NotificationList(BaseModel):
    items: List[NotificationItem] = []
    unread: int = 0


class UnreadCount(BaseModel):
    unread: int = 0
