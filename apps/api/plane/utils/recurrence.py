# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Aight fork: schedule maths for recurring stories.

A rule fires at 08:00 project-local time on every matching day. Weekdays are 0 = Mon … 6 = Sun.
Monthly rules on a day the month lacks (29–31) fire on the month's last day.
"""

import calendar
import datetime as dt

FREQUENCIES = ("daily", "weekdays", "weekly", "monthly")
FIRE_TIME = dt.time(8, 0)
DAY_NAMES = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
# 400 days covers every frequency (worst case: monthly, ~31 days)
SEARCH_DAYS = 400


def matches(rule, day):
    if rule.frequency == "daily":
        return True
    if rule.frequency == "weekdays":
        return day.weekday() < 5
    if rule.frequency == "weekly":
        return day.weekday() in rule.weekdays
    if rule.frequency == "monthly":
        last_day = calendar.monthrange(day.year, day.month)[1]
        return day.day == min(rule.day_of_month, last_day)
    raise ValueError(f"unknown frequency {rule.frequency!r}")


def next_occurrence(rule, after, tz):
    """First 08:00 project-local instant strictly after `after` that matches the rule, in UTC."""
    day = after.astimezone(tz).date()
    for _ in range(SEARCH_DAYS):
        candidate = dt.datetime.combine(day, FIRE_TIME, tzinfo=tz)
        if candidate > after and matches(rule, day):
            return candidate.astimezone(dt.timezone.utc)
        day += dt.timedelta(days=1)
    raise ValueError("rule never fires")


def summary(rule):
    if rule.frequency == "weekly":
        return "weekly on " + ", ".join(DAY_NAMES[d] for d in sorted(rule.weekdays))
    if rule.frequency == "monthly":
        return f"monthly on day {rule.day_of_month}"
    return rule.frequency
