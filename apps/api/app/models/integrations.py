from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Identity, Integer, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class Webhook(Base):
    """An address told about ingests, answers and gaps. Each delivery is signed with its
    secret (X-Atlas-Signature-256: sha256=HMAC of the body)."""

    __tablename__ = "webhooks"

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    url: Mapped[str] = mapped_column(Text)
    secret: Mapped[str] = mapped_column(Text)
    events: Mapped[list] = mapped_column(JSONB, default=list)  # "ingest", "query", "gap"
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_status: Mapped[int | None] = mapped_column(Integer)  # 0: it could not be reached
    last_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
