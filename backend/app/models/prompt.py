from sqlalchemy import Column, String, ForeignKey, Boolean, JSON
from sqlalchemy.orm import relationship
from app.models.base import BaseSchema

class Prompt(BaseSchema):
    __tablename__ = 'prompts'

    title = Column(String, nullable=True)
    text = Column(String, nullable=False)
    user_id = Column(String(36), ForeignKey('users.id'), nullable=True)
    organization_id = Column(String(36), ForeignKey('organizations.id'), nullable=True)

    # ── completion-shaped execution spec (all NULLABLE so pre-existing rows survive) ──
    mode = Column(String, nullable=True, default='chat')     # 'chat' | 'deep' | 'training'
    model_id = Column(String(36), nullable=True)             # LLM override; null = org default
    mentions = Column(JSON, nullable=True)                    # PromptSchema.mentions
    parameters = Column(JSON, nullable=True)                  # [{name,label,type,required,default,options}]

    # ── scope / classification ──
    scope = Column(String, nullable=True, default='agent')     # 'agent' | 'global' | 'private'
    is_starter = Column(Boolean, nullable=True, default=False)  # surface as a conversation starter

    # Keep the relationship, but reference Organization by string to avoid circular imports
    organization = relationship("Organization", back_populates="prompts")
