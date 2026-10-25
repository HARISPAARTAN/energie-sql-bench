"""Typed settings from config.toml, pricing.toml, .env and environment variables."""

from __future__ import annotations

import os
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from pathlib import Path

ENV_KEYS = frozenset(
    {
        "ESB_DB_SERVER",
        "ESB_DB_NAME",
        "ESB_DB_USER",
        "ESB_DB_PASSWORD",
        "ANTHROPIC_API_KEY",
        "OLLAMA_HOST",
        "MSSQL_SA_PASSWORD",
    }
)


def find_root(start: Path | None = None) -> Path:
    """The repository root: the nearest folder upwards that holds config.toml and pyproject.toml."""
    env_root = os.environ.get("ESB_ROOT")
    if env_root:
        return Path(env_root).resolve()
    here = (start or Path.cwd()).resolve()
    for candidate in (here, *here.parents):
        if (candidate / "config.toml").is_file() and (candidate / "pyproject.toml").is_file():
            return candidate
    raise FileNotFoundError("config.toml nicht gefunden: im Projektordner ausführen oder ESB_ROOT setzen")


def read_dotenv(path: Path) -> dict[str, str]:
    """KEY=VALUE lines of a .env file; comments and blank lines are skipped. Values are never logged."""
    values: dict[str, str] = {}
    if not path.is_file():
        return values
    for raw in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        values[key.strip()] = value
    return values


def odbc_quote(value: str) -> str:
    """An ODBC connection-string value in braces; a closing brace is doubled."""
    return "{" + value.replace("}", "}}") + "}"


@dataclass(frozen=True)
class DbSettings:
    server: str
    name: str
    sample_name: str
    driver: str
    user: str
    password: str = field(repr=False)
    query_timeout_s: int = 30
    lock_timeout_ms: int = 5000
    max_rows: int = 10000

    def connection_string(self, database: str | None = None) -> str:
        if not self.password:
            raise ValueError("ESB_DB_PASSWORD fehlt: .env anlegen (tools/setup_reader.py)")
        return (
            f"DRIVER={{{self.driver}}};SERVER={self.server};DATABASE={database or self.name};"
            f"UID={odbc_quote(self.user)};PWD={odbc_quote(self.password)};"
            "Encrypt=yes;TrustServerCertificate=yes"
        )

    def with_overrides(self, **changes: object) -> DbSettings:
        return replace(self, **changes)


@dataclass(frozen=True)
class SnapshotSettings:
    as_of: str
    smard_start: str
    smard_end: str
    mastr_end: str
    mastr_export: str
    monitor_commit: str

    @property
    def smard_start_key(self) -> int:
        return int(self.smard_start.replace("-", ""))

    @property
    def smard_end_key(self) -> int:
        return int(self.smard_end.replace("-", ""))

    @property
    def mastr_end_key(self) -> int:
        """datum_key of the first day of the last MaStR month (fact_kapazitaet keys months by day 1)."""
        return int(self.mastr_end.replace("-", "")) * 100 + 1


@dataclass(frozen=True)
class VariantSpec:
    id: str
    schema: str  # full | oracle | retrieved
    semantic: bool
    fewshot: bool


@dataclass(frozen=True)
class CompareSettings:
    rel_tol: float
    abs_tol: float


@dataclass(frozen=True)
class AnthropicSettings:
    models: tuple[str, ...]
    effort: str
    max_tokens: int
    cache: bool


@dataclass(frozen=True)
class OllamaSettings:
    host: str
    model: str
    num_ctx: int
    seed: int


@dataclass(frozen=True)
class CostSettings:
    eur_usd: float
    rate_date: str
    max_run_usd: float


@dataclass(frozen=True)
class PlannedConfig:
    provider: str
    model: str
    variant: str
    self_correct: bool

    @classmethod
    def parse(cls, text: str) -> PlannedConfig:
        provider, model, variant, self_correct = text.split("|")
        return cls(provider, model, variant, self_correct == "1")

    @property
    def key(self) -> str:
        return f"{self.provider}|{self.model}|{self.variant}|{int(self.self_correct)}"


@dataclass(frozen=True)
class ReportSettings:
    leaderboard_de: str
    leaderboard_en: str
    site_dir: str
    planned: tuple[PlannedConfig, ...]
    comparisons: tuple[tuple[str, str], ...]


@dataclass(frozen=True)
class ModelPrice:
    provider: str
    input: float
    cache_write: float
    cache_read: float
    output: float
    source: str
    verified: str


@dataclass(frozen=True)
class Settings:
    root: Path
    db: DbSettings
    snapshot: SnapshotSettings
    languages: tuple[str, ...]
    default_split: str
    gold_max_rows: int
    variants: dict[str, VariantSpec]
    compare: CompareSettings
    anthropic: AnthropicSettings
    ollama: OllamaSettings
    cost: CostSettings
    report: ReportSettings
    pricing: dict[str, ModelPrice]
    env: dict[str, str] = field(repr=False)

    def path(self, relative: str) -> Path:
        return self.root / relative


def _comparison(text: str) -> tuple[str, str]:
    left, _, right = text.partition(" vs ")
    return left.strip(), right.strip()


def load_settings(root: Path | None = None, environ: Mapping[str, str] | None = None) -> Settings:
    root = (root or find_root()).resolve()
    cfg = tomllib.loads((root / "config.toml").read_text(encoding="utf-8"))
    prices = tomllib.loads((root / "pricing.toml").read_text(encoding="utf-8"))
    env = {k: v for k, v in read_dotenv(root / ".env").items() if v}  # blank values keep the defaults
    source = os.environ if environ is None else environ
    env.update({k: v for k, v in source.items() if k in ENV_KEYS and v})
    d = cfg["database"]
    db = DbSettings(
        server=env.get("ESB_DB_SERVER", d["server"]),
        name=env.get("ESB_DB_NAME", d["name"]),
        sample_name=d["sample_name"],
        driver=d["driver"],
        user=env.get("ESB_DB_USER", d["user"]),
        password=env.get("ESB_DB_PASSWORD", ""),
        query_timeout_s=int(d["query_timeout_s"]),
        lock_timeout_ms=int(d["lock_timeout_ms"]),
        max_rows=int(d["max_rows"]),
    )
    s = cfg["snapshot"]
    variants = {
        vid: VariantSpec(vid, v["schema"], bool(v["semantic"]), bool(v["fewshot"]))
        for vid, v in sorted(cfg["variants"].items())
    }
    a = cfg["providers"]["anthropic"]
    o = cfg["providers"]["ollama"]
    c = cfg["cost"]
    r = cfg["report"]
    pricing = {
        model: ModelPrice(
            p["provider"],
            float(p["input"]),
            float(p["cache_write"]),
            float(p["cache_read"]),
            float(p["output"]),
            p["source"],
            p["verified"],
        )
        for model, p in prices["models"].items()
    }
    return Settings(
        root=root,
        db=db,
        snapshot=SnapshotSettings(
            s["as_of"],
            s["smard_start"],
            s["smard_end"],
            s["mastr_end"],
            s["mastr_export"],
            s["monitor_commit"],
        ),
        languages=tuple(cfg["bench"]["languages"]),
        default_split=cfg["bench"]["default_split"],
        gold_max_rows=int(cfg["bench"]["gold_max_rows"]),
        variants=variants,
        compare=CompareSettings(float(cfg["compare"]["rel_tol"]), float(cfg["compare"]["abs_tol"])),
        anthropic=AnthropicSettings(tuple(a["models"]), a["effort"], int(a["max_tokens"]), bool(a["cache"])),
        ollama=OllamaSettings(
            env.get("OLLAMA_HOST", o["host"]), o["model"], int(o["num_ctx"]), int(o["seed"])
        ),
        cost=CostSettings(float(c["eur_usd"]), c["rate_date"], float(c["max_run_usd"])),
        report=ReportSettings(
            r["leaderboard_de"],
            r["leaderboard_en"],
            r["site_dir"],
            tuple(PlannedConfig.parse(x) for x in r["planned"]),
            tuple(_comparison(x) for x in r["comparisons"]),
        ),
        pricing=pricing,
        env=env,
    )
