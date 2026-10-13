# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Aight fork: schedule maths for recurring stories."""

import datetime as dt
import zoneinfo
from types import SimpleNamespace

import pytest

from plane.utils.recurrence import next_occurrence, summary

BKK = zoneinfo.ZoneInfo("Asia/Bangkok")
LON = zoneinfo.ZoneInfo("Europe/London")
UTC = dt.timezone.utc


def rule(frequency, weekdays=None, day_of_month=None):
    return SimpleNamespace(frequency=frequency, weekdays=weekdays or [], day_of_month=day_of_month)


def bkk(y, m, d, h=0, mi=0):
    return dt.datetime(y, m, d, h, mi, tzinfo=BKK)


@pytest.mark.unit
class TestNextOccurrence:
    def test_daily_before_eight_fires_today(self):
        # Mon 13 Oct 2026 07:59 BKK → same day 08:00 BKK = 01:00 UTC
        assert next_occurrence(rule("daily"), bkk(2026, 10, 13, 7, 59), BKK) == dt.datetime(2026, 10, 13, 1, 0, tzinfo=UTC)

    def test_daily_at_eight_exactly_moves_to_tomorrow(self):
        assert next_occurrence(rule("daily"), bkk(2026, 10, 13, 8, 0), BKK) == dt.datetime(2026, 10, 14, 1, 0, tzinfo=UTC)

    def test_result_is_utc(self):
        assert next_occurrence(rule("daily"), bkk(2026, 10, 13), BKK).tzinfo == UTC

    def test_weekdays_skips_weekend(self):
        # Fri 16 Oct 2026 09:00 → Mon 19 Oct 08:00
        assert next_occurrence(rule("weekdays"), bkk(2026, 10, 16, 9), BKK) == bkk(2026, 10, 19, 8).astimezone(UTC)

    def test_weekly_on_friday(self):
        # Tue 13 Oct → Fri 16 Oct (weekday 4)
        assert next_occurrence(rule("weekly", [4]), bkk(2026, 10, 13, 12), BKK) == bkk(2026, 10, 16, 8).astimezone(UTC)

    def test_weekly_multiple_days_picks_nearest(self):
        # Tue 13 Oct 12:00, days Mon+Wed → Wed 14 Oct
        assert next_occurrence(rule("weekly", [0, 2]), bkk(2026, 10, 13, 12), BKK) == bkk(2026, 10, 14, 8).astimezone(UTC)

    def test_weekly_wraps_to_next_week(self):
        # Sat 17 Oct, Mon only → Mon 19 Oct
        assert next_occurrence(rule("weekly", [0]), bkk(2026, 10, 17, 12), BKK) == bkk(2026, 10, 19, 8).astimezone(UTC)

    def test_monthly_first(self):
        assert next_occurrence(rule("monthly", day_of_month=1), bkk(2026, 10, 13), BKK) == bkk(2026, 11, 1, 8).astimezone(UTC)

    def test_monthly_31_clamps_in_30_day_month(self):
        # November has 30 days → 30 Nov
        assert next_occurrence(rule("monthly", day_of_month=31), bkk(2026, 11, 1), BKK) == bkk(2026, 11, 30, 8).astimezone(UTC)

    def test_monthly_31_clamps_february(self):
        assert next_occurrence(rule("monthly", day_of_month=31), bkk(2027, 2, 1), BKK) == bkk(2027, 2, 28, 8).astimezone(UTC)

    def test_monthly_29_non_leap_feb(self):
        assert next_occurrence(rule("monthly", day_of_month=29), bkk(2027, 2, 1), BKK) == bkk(2027, 2, 28, 8).astimezone(UTC)

    def test_monthly_29_leap_feb(self):
        assert next_occurrence(rule("monthly", day_of_month=29), bkk(2028, 2, 1), BKK) == bkk(2028, 2, 29, 8).astimezone(UTC)

    def test_monthly_after_clamped_day_goes_to_next_month(self):
        # Fired 30 Nov (clamped 31) → next is 31 Dec
        after = bkk(2026, 11, 30, 8)
        assert next_occurrence(rule("monthly", day_of_month=31), after, BKK) == bkk(2026, 12, 31, 8).astimezone(UTC)

    def test_dst_zone_keeps_local_eight(self):
        # London switches to GMT on 25 Oct 2026: 08:00 local is 07:00 UTC before, 08:00 UTC after
        before = next_occurrence(rule("daily"), dt.datetime(2026, 10, 23, 9, tzinfo=LON), LON)
        after = next_occurrence(rule("daily"), dt.datetime(2026, 10, 25, 9, tzinfo=LON), LON)
        assert before == dt.datetime(2026, 10, 24, 7, 0, tzinfo=UTC)
        assert after == dt.datetime(2026, 10, 26, 8, 0, tzinfo=UTC)


@pytest.mark.unit
class TestSummary:
    def test_summaries(self):
        assert summary(rule("daily")) == "daily"
        assert summary(rule("weekdays")) == "weekdays"
        assert summary(rule("weekly", [4, 0])) == "weekly on Mon, Fri"
        assert summary(rule("monthly", day_of_month=1)) == "monthly on day 1"
