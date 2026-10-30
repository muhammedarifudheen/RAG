from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Identity, Integer, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class KnowledgeAudit(Base):
    """A health check of the whole knowledge base: a model's table of each source's
    coverage, staleness, overlap and gaps. The newest is shown on the Health page."""

    __tablename__ = "knowledge_audits"

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    report: Mapped[str] = mapped_column(Text)
    model: Mapped[str] = mapped_column(Text)
    sources: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
