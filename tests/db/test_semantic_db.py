"""Live check of the semantic layer: every template runs on the warehouse and the glossary's reconciliation values hold."""

from decimal import Decimal

import pytest

from energie_sql_bench.config import Settings
from energie_sql_bench.execute import MssqlExecutor
from energie_sql_bench.semantic import load_semantic

pytestmark = pytest.mark.db

VALUES = {
    "{von}": "20250101",
    "{bis}": "20251231",
    "{von_vorjahr}": "20240101",
    "{bis_vorjahr}": "20241231",
    "{jahr}": "2025",
    "{monat}": "2025-12",
    "{vormonat}": "2025-11",
    "{monatserster}": "20251201",
    "{et}": "Photovoltaik",
}


def filled(settings: Settings, measure_id: str, **overrides: str) -> str:
    layer = load_semantic(settings.path("semantic/measures.yaml"))
    sql = next(m.sql for m in layer.measures if m.id == measure_id)
    for key, value in {**VALUES, **{"{" + k + "}": v for k, v in overrides.items()}}.items():
        sql = sql.replace(key, value)
    return sql


def scalar(reader: MssqlExecutor, sql: str) -> object:
    result = reader.run(sql)
    assert result.ok, result.error
    assert result.result is not None and len(result.result.rows) == 1
    return result.result.rows[0][0]


def test_every_template_executes(settings: Settings, reader: MssqlExecutor) -> None:
    layer = load_semantic(settings.path("semantic/measures.yaml"))
    for measure in layer.measures:
        result = reader.run(filled(settings, measure.id))
        assert result.ok, (measure.id, result.error)
        assert len(result.result.rows) == 1, measure.id


# Values from the monitor's reconciliation (docs/kpi-glossar.md, section Abgleich mit dem Data Warehouse, 2026-10-25).
@pytest.mark.parametrize(
    ("measure_id", "overrides", "expected", "tolerance"),
    [
        ("erzeugung_mwh", {}, Decimal("439280977"), Decimal("0.5")),
        ("ee_anteil_prozent", {}, Decimal("58.95"), Decimal("0.05")),
        ("negative_preisstunden", {}, Decimal("573"), Decimal("0")),
        ("day_ahead_avg", {}, Decimal("89.32"), Decimal("0.005")),
        ("installierte_leistung_mw", {"bis": "20241231"}, Decimal("267978"), Decimal("0.5")),
        ("volllaststunden_h", {"et": "Wind Onshore"}, Decimal("1634"), Decimal("0.5")),
    ],
)
def test_glossary_reconciliation(
    settings: Settings,
    reader: MssqlExecutor,
    measure_id: str,
    overrides: dict[str, str],
    expected: Decimal,
    tolerance: Decimal,
) -> None:
    value = Decimal(str(scalar(reader, filled(settings, measure_id, **overrides))))
    assert abs(value - expected) <= tolerance, (measure_id, value)


def test_installed_capacity_takes_last_month_with_data(settings: Settings, reader: MssqlExecutor) -> None:
    december = scalar(reader, filled(settings, "installierte_leistung_mw", bis="20241231"))
    mid_december = scalar(reader, filled(settings, "installierte_leistung_mw", bis="20241215"))
    november = scalar(reader, filled(settings, "installierte_leistung_mw", bis="20241130"))
    assert mid_december == december  # a single day inside December still reads the December stock
    assert november != december


def test_full_load_hours_use_months_of_generation(settings: Settings, reader: MssqlExecutor) -> None:
    year = scalar(reader, filled(settings, "volllaststunden_h", et="Wind Onshore"))
    # A period that starts before the data (2022-10-01) only counts the months with generation, so it equals 2023 alone.
    wide = scalar(
        reader, filled(settings, "volllaststunden_h", et="Wind Onshore", von="20221001", bis="20231231")
    )
    narrow = scalar(
        reader, filled(settings, "volllaststunden_h", et="Wind Onshore", von="20230101", bis="20231231")
    )
    assert year is not None and wide == narrow
    assert (
        scalar(
            reader, filled(settings, "volllaststunden_h", et="Wind Onshore", von="20220101", bis="20221231")
        )
        is None
    )
