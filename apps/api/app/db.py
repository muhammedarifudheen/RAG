from collections.abc import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.config import settings

# Without a connect timeout, psycopg waits indefinitely when the port drops packets.
engine = create_engine(
    settings.database_url, pool_pre_ping=True, connect_args={"connect_timeout": 5}
)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_db() -> Iterator[Session]:
    with SessionLocal() as session:
        yield session
