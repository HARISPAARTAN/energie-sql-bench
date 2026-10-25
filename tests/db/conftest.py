from collections.abc import Iterator
from pathlib import Path

import pytest

from energie_sql_bench.config import Settings, load_settings
from energie_sql_bench.execute import MssqlExecutor

REPO = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="session")
def settings() -> Settings:
    s = load_settings(REPO)
    if not s.db.password:
        pytest.skip("ESB_DB_PASSWORD fehlt in .env")
    return s


@pytest.fixture
def reader(settings: Settings) -> Iterator[MssqlExecutor]:
    executor = MssqlExecutor(settings.db)
    yield executor
    executor.close()
