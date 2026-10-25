from pathlib import Path

from energie_sql_bench.files import read_yaml

REPO = Path(__file__).resolve().parents[2]


def test_twenty_distinct_redteam_prompts() -> None:
    prompts = read_yaml(REPO / "bench" / "redteam" / "prompts.yaml")["prompts"]
    assert len(prompts) == 20
    assert len({p["id"] for p in prompts}) == 20
    assert len({p["de"] for p in prompts}) == 20
