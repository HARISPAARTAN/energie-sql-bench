from energie_sql_bench.llm.base import Request
from energie_sql_bench.llm.synthetic import SYNTHETIC_MODEL, SyntheticProvider, behaviour
from energie_sql_bench.prompts import ABSTAIN_TOKEN
from energie_sql_bench.questions import Question

ROWS = Question.model_validate(
    {
        "id": "q001",
        "split": "test",
        "tier": "T1",
        "de": "Preis?",
        "en": "Price?",
        "expect": "rows",
        "gold_sql": "SELECT AVG(day_ahead_eur_mwh) AS a FROM dw.fact_preis",
        "check_sql": "SELECT 1",
        "tables": ["dw.fact_preis"],
        "notes": "n",
    }
)
ABSTAIN = Question.model_validate(
    {
        "id": "q010",
        "split": "test",
        "tier": "A",
        "de": "Redispatch?",
        "en": "Redispatch?!",
        "expect": "abstain",
        "notes": "n",
    }
)


def request(item_id: str, attempt: int = 0) -> Request:
    return Request(item_id, SYNTHETIC_MODEL, "S", (("user", "x"),), "h", 0, attempt)


def test_behaviour_is_deterministic() -> None:
    assert behaviour("q001-de") == behaviour("q001-de")
    assert {behaviour(f"q{n:03d}-de") for n in range(1, 61)} == set(range(10))


def test_answers_follow_behaviour() -> None:
    provider = SyntheticProvider([ROWS, ABSTAIN])
    h = behaviour("q001-de")
    text = provider.complete(request("q001-de")).text
    if h <= 5:
        assert ROWS.gold_sql in text
    elif h == 6:
        assert "LIMIT 10" in text
    elif h == 7:
        assert "erzeugung_gwh" in text
    elif h == 8:
        assert "DELETE" in text
    else:
        assert text == ABSTAIN_TOKEN
    assert ROWS.gold_sql in provider.complete(request("q001-de", attempt=1)).text


def test_every_behaviour_branch_is_reachable_with_a_fixed_item() -> None:
    provider = SyntheticProvider([ROWS])
    seen: dict[int, str] = {}
    for n in range(1, 400):
        item_id = f"q001-x{n}"
        seen.setdefault(behaviour(item_id), provider.complete(request(item_id)).text)
    assert ROWS.gold_sql in seen[0] and ROWS.gold_sql in seen[5]
    assert seen[6].endswith("LIMIT 10\n```")
    assert "erzeugung_gwh" in seen[7]
    assert seen[8].startswith("```sql\nDELETE")
    assert seen[9] == ABSTAIN_TOKEN


def test_abstain_items() -> None:
    provider = SyntheticProvider([ROWS, ABSTAIN])
    for lang in ("de", "en"):
        text = provider.complete(request(f"q010-{lang}")).text
        assert ("dim_region" in text) == (behaviour(f"q010-{lang}") == 0)


def test_usage_is_zero_and_described() -> None:
    provider = SyntheticProvider([ROWS])
    assert provider.complete(request("q001-en")).usage.output_tokens == 0
    assert provider.describe()["model"] == SYNTHETIC_MODEL
