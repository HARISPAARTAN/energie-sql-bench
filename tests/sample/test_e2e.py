from pathlib import Path

import pytest

from energie_sql_bench.config import load_settings
from energie_sql_bench.execute import DuckDbExecutor
from energie_sql_bench.files import read_json
from energie_sql_bench.gold import load_gold
from energie_sql_bench.llm.synthetic import SYNTHETIC_MODEL, SyntheticProvider, behaviour
from energie_sql_bench.questions import build_items
from energie_sql_bench.runner import BenchContext, RunSpec, execute_run, load_context
from energie_sql_bench.sample import load_duckdb

REPO = Path(__file__).resolve().parents[2]
SAMPLE = REPO / "data" / "sample"
SETTINGS = load_settings(REPO, environ={})


@pytest.fixture(scope="module")
def setup():  # noqa: ANN201
    base = load_context(SETTINGS)
    ctx = BenchContext(base.questions, load_gold(SAMPLE / "gold_mssql"), base.prompt)
    parity = {row["id"]: row for row in read_json(SAMPLE / "parity.json")["rows"]}
    items = [
        item
        for item in build_items(ctx.questions, "test", ("de", "en"))
        if item.question.expect == "rows"
        and parity.get(item.question.id, {}).get("status") == "match"
        and parity[item.question.id]["nontrivial"]
        and behaviour(item.item_id) != 6
    ][:10]
    con = load_duckdb(SAMPLE)
    yield ctx, items, con
    con.close()


def run(setup, self_correct: bool):  # noqa: ANN001, ANN201
    ctx, items, con = setup
    spec = RunSpec(
        "e2e", "synthetic", SYNTHETIC_MODEL, "v4", langs=("de", "en"), self_correct=self_correct, max_usd=1.0
    )
    return execute_run(
        spec,
        SETTINGS.variants["v4"],
        ctx,
        SyntheticProvider(ctx.questions),
        DuckDbExecutor(con),
        SETTINGS.pricing[SYNTHETIC_MODEL],
        SETTINGS.compare,
        items,
    )


def test_ten_items_selected(setup) -> None:  # noqa: ANN001
    assert len(setup[1]) == 10


def test_single_shot_on_duckdb(setup) -> None:  # noqa: ANN001
    result = run(setup, self_correct=False)
    assert result.complete and len(result.outcomes) == 10
    for outcome in result.outcomes:
        h = behaviour(outcome.item_id)
        assert outcome.correct == (h <= 5), outcome.item_id
        expected_status = {7: "db_error", 8: "blocked", 9: "abstain"}.get(h, "ok")
        assert outcome.final_status == expected_status, outcome.item_id


def test_self_correction_on_duckdb(setup) -> None:  # noqa: ANN001
    result = run(setup, self_correct=True)
    for outcome in result.outcomes:
        h = behaviour(outcome.item_id)
        assert outcome.correct == (h != 9), outcome.item_id
        assert len(outcome.attempts) == (2 if h in (7, 8) else 1), outcome.item_id
