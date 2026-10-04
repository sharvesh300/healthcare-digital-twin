from datetime import date

import pandas as pd

from twin.sources.cgmacros import shift


def test_shift_preserves_wall_clock_time():
    idx = pd.DatetimeIndex(["2020-05-01 10:30", "2020-05-01 23:59"])
    out = shift(idx, (date(2026, 8, 16) - date(2020, 5, 1)).days, "America/Chicago")
    assert [t.strftime("%Y-%m-%d %H:%M") for t in out] == ["2026-08-16 10:30", "2026-08-16 23:59"]
    assert str(out.tz) == "America/Chicago"


def test_shift_across_dst_keeps_local_time():
    # 2026-11-01 is the DST fall-back date in the US; 08:00 must stay 08:00 local.
    out = shift(pd.DatetimeIndex(["2020-10-25 08:00"]), (date(2026, 11, 1) - date(2020, 10, 25)).days, "America/Chicago")
    assert out[0].strftime("%Y-%m-%d %H:%M") == "2026-11-01 08:00"
    assert out[0].utcoffset() == pd.Timedelta(hours=-6)


def test_nonexistent_and_ambiguous_times_are_dropped_not_collided():
    # 02:30 on spring-forward day does not exist; 01:30 on fall-back day is ambiguous. Both
    # become NaT (dropped) so they cannot collide with real readings at 03:00 / 01:30.
    out = shift(pd.DatetimeIndex(["2026-03-08 02:30", "2026-03-08 03:00", "2026-11-01 01:30"]), 0, "America/Chicago")
    assert pd.isna(out[0]) and out[1].strftime("%H:%M") == "03:00" and pd.isna(out[2])
