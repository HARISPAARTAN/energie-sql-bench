import datetime as dt
import struct

from energie_sql_bench.execute import SQL_SS_TIMESTAMPOFFSET, datetimeoffset_from_bytes
from energie_sql_bench.resultset import ResultSet, infer_types


def pack(year, month, day, hour, minute, second, nanoseconds, tz_hour, tz_minute) -> bytes:
    return struct.pack("<6hI2h", year, month, day, hour, minute, second, nanoseconds, tz_hour, tz_minute)


def test_sql_type_code_is_the_ss_timestampoffset() -> None:
    assert SQL_SS_TIMESTAMPOFFSET == -155


def test_decodes_positive_offset() -> None:
    value = datetimeoffset_from_bytes(pack(2025, 10, 4, 23, 0, 0, 0, 2, 0))
    assert value == dt.datetime(2025, 10, 4, 23, 0, tzinfo=dt.timezone(dt.timedelta(hours=2)))
    assert value.utcoffset() == dt.timedelta(hours=2)


def test_decodes_negative_offset_with_minutes_and_fraction() -> None:
    value = datetimeoffset_from_bytes(pack(2025, 1, 4, 21, 0, 0, 123_456_700, -3, -30))
    assert value.utcoffset() == -dt.timedelta(hours=3, minutes=30)
    assert value.microsecond == 123456


def test_aware_datetime_survives_the_result_json() -> None:
    value = datetimeoffset_from_bytes(pack(2025, 10, 4, 23, 0, 0, 0, 2, 0))
    rows = [[value]]
    result = ResultSet(["lokal"], infer_types(rows, 1), rows)
    assert result.to_json()["rows"] == [["2025-10-04T23:00:00+02:00"]]
    assert ResultSet.from_json(result.to_json()) == result
