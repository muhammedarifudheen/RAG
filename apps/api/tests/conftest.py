import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from seed import FakeEmbedder, seed
from sqlalchemy import Engine, create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker

from app.db import get_db
from app.embedding import get_embedder
from app.llm import LLMAnswer, get_answerer
from app.main import app
from app.ratelimit import limiter
from app.schemas import CodeChunk

API_ROOT = Path(__file__).resolve().parent.parent


# The database docker-compose creates next to the development one.
DEFAULT_TEST_DATABASE_URL = "postgresql+psycopg://atlas:atlas@localhost:5432/atlas_test"


@pytest.fixture(scope="session")
def database_url() -> str:
    """URL of a Postgres database with pgvector available, reserved for tests.

    The tests truncate the tables, so the database name must end in `_test`.
    Tests that need it are skipped when it cannot be reached.
    """
    url = os.environ.get("TEST_DATABASE_URL", DEFAULT_TEST_DATABASE_URL)
    if not (make_url(url).database or "").endswith("_test"):
        raise pytest.UsageError(
            "TEST_DATABASE_URL must point at a database whose name ends in '_test'."
        )

    probe = create_engine(url, connect_args={"connect_timeout": 3})
    try:
        with probe.connect():
            pass
    except OperationalError as error:
        reason = str(error.orig).strip().splitlines()[0][:200]
        pytest.skip(f"Test database unavailable at {make_url(url).render_as_string()}: {reason}")
    finally:
        probe.dispose()
    return url


@pytest.fixture(scope="session")
def engine(database_url: str) -> Iterator[Engine]:
    """The fixture database: schema from the real migrations, data from seed.py."""
    config = Config(str(API_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(API_ROOT / "migrations"))
    config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))
    command.upgrade(config, "head")

    engine = create_engine(database_url)
    with Session(engine) as session, session.begin():
        seed(session)
    yield engine
    engine.dispose()


@pytest.fixture
def db(engine: Engine) -> Iterator[Session]:
    with Session(engine) as session:
        yield session


class FakeAnswerer:
    """Stands in for Claude: returns a canned reply and records what it was asked."""

    def __init__(self) -> None:
        self.reply = "No answer configured."
        self.error: Exception | None = None
        self.calls: list[tuple[str, list[CodeChunk]]] = []

    def answer(self, question: str, chunks: list[CodeChunk]) -> LLMAnswer:
        self.calls.append((question, chunks))
        if self.error is not None:
            raise self.error
        return LLMAnswer(text=self.reply, model="fake-model")


@pytest.fixture
def answerer() -> FakeAnswerer:
    return FakeAnswerer()


@pytest.fixture(autouse=True)
def _reset_app_state() -> Iterator[None]:
    limiter.reset()
    yield
    app.dependency_overrides.clear()
    limiter.reset()


@pytest.fixture
def plain_client() -> Iterator[TestClient]:
    """A client for endpoints that need no database."""
    with TestClient(app) as client:
        yield client


@pytest.fixture
def client(engine: Engine, answerer: FakeAnswerer) -> Iterator[TestClient]:
    """A client wired to the fixture database, a fake embedder and a fake Claude."""
    factory = sessionmaker(bind=engine)

    def override_db() -> Iterator[Session]:
        with factory() as session:
            yield session

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_embedder] = FakeEmbedder
    app.dependency_overrides[get_answerer] = lambda: answerer
    with TestClient(app) as test_client:
        yield test_client
