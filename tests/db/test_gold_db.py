from functools import partial

import pytest

from energie_sql_bench.config import Settings
from energie_sql_bench.execute import MssqlExecutor, connect_mssql, fetch_all
from energie_sql_bench.files import read_json
from energie_sql_bench.gold import build_gold
from energie_sql_bench.questions import load_questions
from energie_sql_bench.snapshot import compare_fingerprints, compute_fingerprint

pytestmark = pytest.mark.db


def test_live_fingerprint_matches(settings: Settings) -> None:
    con = connect_mssql(settings.db)
    try:
        live = compute_fingerprint(partial(fetch_all, con), settings.snapshot)
    finally:
        con.close()
    assert compare_fingerprints(read_json(settings.path("snapshot/fingerprint.json")), live) == []


def test_gold_is_reproducible(settings: Settings) -> None:
    questions = load_questions(settings.path("bench/questions"))
    digest = read_json(settings.path("snapshot/fingerprint.json"))["digest"]
    executor = MssqlExecutor(settings.db)
    try:
        entries, errors = build_gold(questions, executor, digest, settings.gold_max_rows, settings.compare)
    finally:
        executor.close()
    assert errors == []
    for qid, entry in entries.items():
        assert entry.to_json() == read_json(settings.path(f"bench/gold/{qid}.json"))
