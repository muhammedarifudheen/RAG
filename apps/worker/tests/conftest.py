import pytest
from support import FIXTURE_REPO

from worker.extract import FileExtraction
from worker.pipeline import ParsedRepo, parse_repo


@pytest.fixture(scope="session")
def repo() -> ParsedRepo:
    return parse_repo(FIXTURE_REPO)


@pytest.fixture(scope="session")
def files(repo: ParsedRepo) -> dict[str, FileExtraction]:
    return {f.path: f for f in repo.files}
