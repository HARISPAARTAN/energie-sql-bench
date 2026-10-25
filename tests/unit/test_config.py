import shutil
from pathlib import Path

import pytest

from energie_sql_bench.config import PlannedConfig, load_settings, odbc_quote, read_dotenv

REPO = Path(__file__).resolve().parents[2]


@pytest.fixture
def tmp_root(tmp_path: Path) -> Path:
    for name in ("config.toml", "pricing.toml", "pyproject.toml"):
        shutil.copy(REPO / name, tmp_path / name)
    return tmp_path


def test_defaults_without_env(tmp_root: Path) -> None:
    s = load_settings(tmp_root, environ={})
    assert s.db.server == "127.0.0.1,1433"
    assert s.db.name == "energiewende"
    assert s.db.sample_name == "energiewende_sample"
    assert s.db.user == "bench_reader"
    assert s.db.password == ""
    assert s.db.max_rows == 10000
    assert s.snapshot.smard_start_key == 20230101
    assert s.snapshot.smard_end_key == 20260930
    assert s.snapshot.mastr_end_key == 20260901
    assert sorted(s.variants) == ["v1", "v2", "v3", "v4", "v5", "v6"]
    assert s.variants["v5"].schema == "oracle"
    assert s.variants["v2"].fewshot is True and s.variants["v2"].semantic is False
    assert s.cost.eur_usd > 0
    assert s.languages == ("de", "en")


def test_dotenv_and_environment_override(tmp_root: Path) -> None:
    (tmp_root / ".env").write_text(
        "ESB_DB_PASSWORD='geheim}1'\nESB_DB_NAME=andere\n# Kommentar\n", encoding="utf-8"
    )
    s = load_settings(tmp_root, environ={"ESB_DB_NAME": "energiewende_sample", "UNRELATED": "x"})
    assert s.db.password == "geheim}1"
    assert s.db.name == "energiewende_sample"
    assert "UNRELATED" not in s.env


def test_password_not_in_repr(tmp_root: Path) -> None:
    (tmp_root / ".env").write_text("ESB_DB_PASSWORD=supersecret\n", encoding="utf-8")
    s = load_settings(tmp_root, environ={})
    assert "supersecret" not in repr(s)


def test_connection_string_quotes_password(tmp_root: Path) -> None:
    (tmp_root / ".env").write_text("ESB_DB_PASSWORD=a}b;c\n", encoding="utf-8")
    cs = load_settings(tmp_root, environ={}).db.connection_string()
    assert "PWD={a}}b;c};" in cs
    assert "DATABASE=energiewende;" in cs
    assert "UID={bench_reader};" in cs
    assert odbc_quote("x") == "{x}"


def test_missing_password_raises(tmp_root: Path) -> None:
    with pytest.raises(ValueError, match="ESB_DB_PASSWORD"):
        load_settings(tmp_root, environ={}).db.connection_string()


def test_planned_comparisons_and_pricing(tmp_root: Path) -> None:
    s = load_settings(tmp_root, environ={})
    assert PlannedConfig.parse("anthropic|claude-haiku-5-5|v4|1").self_correct is True
    keys = [p.key for p in s.report.planned]
    assert len(keys) == 16
    assert "anthropic|claude-haiku-5-5|v4|0" in keys
    assert "ollama|qwen2.5-coder:7b|v5|0" in keys
    assert s.report.comparisons[0] == ("anthropic|claude-haiku-5-5|v1|0", "anthropic|claude-haiku-5-5|v4|0")
    assert s.pricing["claude-haiku-5-5"].input == 0.10
    assert s.pricing["claude-sonnet-5-5"].cache_read == 0.20
    assert s.pricing["synthetic-gold-v1"].output == 0.0


def test_read_dotenv_missing(tmp_path: Path) -> None:
    assert read_dotenv(tmp_path / ".env") == {}
