"""Create or update the bench_reader login and its database users (run as sa).

Usage from the repository root (the sa password is read from the monitor's .env and never printed):
    uv run --env-file ../energiewende-monitor/.env python tools/setup_reader.py
    uv run --env-file ../energiewende-monitor/.env python tools/setup_reader.py --database energiewende_sample
    uv run --env-file ../energiewende-monitor/.env python tools/setup_reader.py --drop

The reader password is generated into the git-ignored .env on first use and reused afterwards.
"""

from __future__ import annotations

import argparse
import os
import secrets
import string
import subprocess
from pathlib import Path

from energie_sql_bench.config import load_settings, read_dotenv
from energie_sql_bench.execute import admin_connect, split_batches

ROOT = Path(__file__).resolve().parents[1]
SYMBOLS = "-_.!@%^*+"
ALPHABET = string.ascii_letters + string.digits + SYMBOLS
MANAGED_KEYS = ("ESB_DB_SERVER", "ESB_DB_NAME", "ESB_DB_USER", "ESB_DB_PASSWORD")


def generate_password(length: int = 32) -> str:
    while True:
        pw = "".join(secrets.choice(ALPHABET) for _ in range(length))
        if (
            any(c.islower() for c in pw)
            and any(c.isupper() for c in pw)
            and any(c.isdigit() for c in pw)
            and any(c in SYMBOLS for c in pw)
        ):
            return pw


def ensure_env_password(env_path: Path) -> str:
    ignored = subprocess.run(["git", "check-ignore", "-q", env_path.name], cwd=ROOT, check=False)
    if ignored.returncode != 0:
        raise SystemExit(".env ist nicht git-ignoriert: abgebrochen")
    existing = read_dotenv(env_path)
    if existing.get("ESB_DB_PASSWORD"):
        return existing["ESB_DB_PASSWORD"]
    pw = generate_password()
    keep = []
    if env_path.exists():
        # utf-8-sig drops a BOM written by Windows PowerShell; the file is written back without one.
        keep = [
            line
            for line in env_path.read_text(encoding="utf-8-sig").splitlines()
            if line.split("=", 1)[0].strip() not in MANAGED_KEYS
        ]
    lines = [
        *keep,
        "ESB_DB_SERVER=127.0.0.1,1433",
        "ESB_DB_NAME=energiewende",
        "ESB_DB_USER=bench_reader",
        f"ESB_DB_PASSWORD={pw}",
    ]
    env_path.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    return pw


def main() -> None:
    parser = argparse.ArgumentParser(description="bench_reader anlegen oder entfernen")
    parser.add_argument("--database", action="append", help="Zieldatenbank (mehrfach möglich)")
    parser.add_argument("--drop", action="store_true", help="Benutzer und Login entfernen")
    args = parser.parse_args()
    sa_password = os.environ.get("MSSQL_SA_PASSWORD")
    if not sa_password:
        raise SystemExit(
            "MSSQL_SA_PASSWORD fehlt: mit uv run --env-file ../energiewende-monitor/.env starten"
        )
    settings = load_settings(ROOT)
    databases = args.database or [settings.db.name]
    setup = ROOT / "sql" / "setup"
    if args.drop:
        user_batch, login_batch = split_batches(
            (setup / "002_drop_bench_reader.sql").read_text(encoding="utf-8")
        )
        for database in databases:
            with admin_connect(settings.db, sa_password, database) as con:
                con.execute(user_batch)
        with admin_connect(settings.db, sa_password, "master") as con:
            con.execute(login_batch)
        print("bench_reader entfernt")
        return
    password = ensure_env_password(ROOT / ".env")
    login_batch, user_batch = split_batches((setup / "001_bench_reader.sql").read_text(encoding="utf-8"))
    with admin_connect(settings.db, sa_password, "master") as con:
        con.execute(login_batch, password)
    for database in databases:
        with admin_connect(settings.db, sa_password, database) as con:
            con.execute(user_batch)
    print(f"bench_reader bereit für: {', '.join(databases)} (Passwort steht in .env)")


if __name__ == "__main__":
    main()
