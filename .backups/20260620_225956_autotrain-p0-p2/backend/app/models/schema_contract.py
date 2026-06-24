from sqlalchemy import Column, String, JSON, Integer, Boolean, Index
from app.models.base import BaseSchema


class SchemaContract(BaseSchema):
    """Versioned column contract per logical dataset.

    On a re-drop we infer the new contract and diff against the active one;
    drift / retype / rename -> quarantine instead of corrupting the table.
    """

    __tablename__ = "schema_contracts"
    __table_args__ = (
        Index("ix_schema_contracts_org_ds_logical", "organization_id", "data_source_id", "logical_dataset"),
    )

    organization_id = Column(String(36), nullable=False, index=True)
    data_source_id = Column(String(36), nullable=True)
    logical_dataset = Column(String, nullable=False)

    version = Column(Integer, nullable=False, default=1, server_default="1")
    columns = Column(JSON, nullable=False, default=list)  # [{name, dtype}]
    active = Column(Boolean, nullable=False, default=True, server_default="1")
