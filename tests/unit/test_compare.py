import datetime as dt
from decimal import Decimal

from energie_sql_bench.compare import compare, is_empty_result, normalize, values_equal
from energie_sql_bench.resultset import ResultSet, infer_types


def rs(rows: list[list], columns: list[str] | None = None, truncated: bool = False) -> ResultSet:
    ncols = len(columns) if columns else (len(rows[0]) if rows else 1)
    cols = columns or [f"c{i}" for i in range(ncols)]
    return ResultSet(cols, infer_types(rows, ncols), rows, truncated)


def test_identical_is_strict_match() -> None:
    c = compare(rs([[Decimal("1.5"), "a"]]), rs([[Decimal("1.5"), "a"]]))
    assert c.match and c.strict and c.extra_columns == 0


def test_column_permutation_and_names_ignored() -> None:
    gold = rs([[Decimal("1.5"), "a"], [Decimal("2"), "b"]], ["wert", "name"])
    pred = rs([["b", Decimal("2")], ["a", Decimal("1.5")]], ["x", "y"])
    c = compare(gold, pred)
    assert c.match and c.strict


def test_extra_column_counts_for_ex_not_strict() -> None:
    c = compare(rs([[Decimal("1")]]), rs([[Decimal("1"), "extra"]]))
    assert c.match and not c.strict and c.extra_columns == 1


def test_fewer_columns_fail() -> None:
    assert not compare(rs([[1, 2]]), rs([[1]])).match


def test_absolute_and_relative_tolerance() -> None:
    assert compare(rs([[Decimal("78.512033")]]), rs([[Decimal("78.51")]])).match
    assert not compare(rs([[Decimal("78.512033")]]), rs([[Decimal("78.50")]])).match
    assert compare(rs([[Decimal("107231652.08")]]), rs([[Decimal("107231660")]])).match
    assert not compare(rs([[Decimal("107231652.08")]]), rs([[Decimal("108000000")]])).match


def test_float_equals_decimal() -> None:
    assert compare(rs([[Decimal("1.5")]]), rs([[1.5]])).match


def test_nulls() -> None:
    assert compare(rs([[None]]), rs([[None]])).match
    assert not compare(rs([[None]]), rs([[0]])).match


def test_rows_are_multisets() -> None:
    gold = rs([[1], [1], [2]])
    assert compare(gold, rs([[2], [1], [1]])).match
    assert not compare(gold, rs([[1], [2], [2]])).match


def test_order_only_when_ordered() -> None:
    gold = rs([[1], [2]])
    pred = rs([[2], [1]])
    assert compare(gold, pred, ordered=False).match
    assert not compare(gold, pred, ordered=True).match


def test_unicode_case_and_whitespace() -> None:
    gold = rs([["Baden-Württemberg"]])
    pred = rs([["baden-wu\u0308rttemberg "]])
    assert compare(gold, pred).match


def test_dates_and_timestamps() -> None:
    assert compare(rs([[dt.datetime(2025, 10, 4, 21, 0)]]), rs([["2025-10-04 21:00"]])).match
    assert compare(rs([[dt.date(2025, 1, 20)]]), rs([[dt.datetime(2025, 1, 20, 0, 0)]])).match
    assert compare(rs([[dt.date(2025, 1, 20)]]), rs([["2025-01-20"]])).match
    assert not compare(rs([[dt.date(2025, 1, 20)]]), rs([["2025-01-21"]])).match


def test_truncated_prediction_is_wrong() -> None:
    assert not compare(rs([[1]]), rs([[1]], truncated=True)).match


def test_row_count_must_match() -> None:
    assert not compare(rs([[1]]), rs([[1], [1]])).match


def test_bool_equals_int() -> None:
    assert compare(rs([[1]]), rs([[True]])).match


def test_columns_must_agree_row_wise() -> None:
    gold = rs([[1, "a"], [2, "b"]])
    pred = rs([[1, "b"], [2, "a"]])
    assert not compare(gold, pred).match


def test_string_is_not_number() -> None:
    assert not values_equal(normalize("1"), normalize(Decimal(1)), 1e-4, 0.005)


def test_is_empty_result() -> None:
    assert is_empty_result(rs([], ["a"]))
    assert is_empty_result(rs([[None]]))
    assert not is_empty_result(rs([[0]]))
    assert is_empty_result(None) is False


def test_abs_tolerance_alone_accepts_small_differences_near_zero() -> None:
    # 0.003 is far above the relative bound (1e-4 * 0.004), so only abs_tol can accept it.
    assert compare(rs([[Decimal("0.001")]]), rs([[Decimal("0.004")]])).match
    assert not compare(rs([[Decimal("0.001")]]), rs([[Decimal("0.007")]])).match
    assert values_equal(Decimal("0.001"), Decimal("0.004"), 0.0, 0.005)
    assert not values_equal(Decimal("0.001"), Decimal("0.004"), 0.0, 0.002)


def test_relative_tolerance_is_measured_against_the_larger_value() -> None:
    # diff 10.0005 is above 1e-4 * 100000 (the smaller value) but below 1e-4 * 100010.0005 (the larger).
    assert values_equal(Decimal("100000"), Decimal("100010.0005"), 1e-4, 0.0)
    assert values_equal(Decimal("100010.0005"), Decimal("100000"), 1e-4, 0.0)
    assert not values_equal(Decimal("100000"), Decimal("100010.5"), 1e-4, 0.0)


def test_a_pred_column_cannot_serve_two_gold_columns() -> None:
    gold = rs([[1, 1], [2, 2]])
    assert not compare(gold, rs([[1, 5], [2, 6]])).match
    assert compare(gold, rs([[1, 1], [2, 2]])).match
    assert compare(gold, rs([[1, 9, 1], [2, 9, 2]])).match


def test_timezone_offsets_are_ignored_and_wall_time_compares() -> None:
    wall = dt.datetime(2025, 10, 4, 23, 0)
    aware = dt.datetime(2025, 10, 4, 23, 0, tzinfo=dt.timezone(dt.timedelta(hours=2)))
    assert normalize(aware) == normalize(wall) == "2025-10-04T23:00:00"
    assert compare(rs([[wall]]), rs([[aware]])).match
