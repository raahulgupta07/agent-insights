from sqlalchemy import Column, String, JSON, Integer, Index
from app.models.base import BaseSchema


class IngestBatch(BaseSchema):
    """One autotrain ingest of a flat file (or a re-drop of a logical dataset).

    Tracks stage -> contract-check -> promote -> autotrain. Lineage stamped on
    the loaded rows themselves (_source_file/_period/_batch_id/...); this row is
    the batch-level audit. No FK constraints by design (tracking table, avoids
    the delete-cascade coupling landmine).
    """

    __tablename__ = "ingest_batches"
    __table_args__ = (
        Index("ix_ingest_batches_hash", "file_hash"),
        Index("ix_ingest_batches_org_ds", "organization_id", "data_source_id"),
    )

    organization_id = Column(String(36), nullable=False, index=True)
    data_source_id = Column(String(36), nullable=True)
    file_id = Column(String(36), nullable=True)

    file_hash = Column(String, nullable=True)
    filename = Column(String, nullable=True)
    logical_dataset = Column(String, nullable=True)
    target_table = Column(String, nullable=True)

    # staged | promoted | quarantined | failed
    status = Column(String(20), nullable=False, default="staged", server_default="staged")
    manifest = Column(JSON, nullable=True)
    row_count = Column(Integer, nullable=False, default=0, server_default="0")
    quarantine_reason = Column(String, nullable=True)
