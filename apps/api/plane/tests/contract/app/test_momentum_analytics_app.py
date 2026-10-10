# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Contract tests for the momentum analytics tiles and charts (Aight fork)."""

import datetime as dt
import statistics

import pytest
from django.utils import timezone
from rest_framework import status

from plane.db.models import (
    Cycle,
    CycleIssue,
    Estimate,
    EstimatePoint,
    Issue,
    IssueActivity,
    IssueType,
    Project,
    ProjectMember,
    State,
)
from plane.utils.sprint import SPRINT_TZ


def week_bounds(offset):
    """Monday 00:00 to Sunday 23:59:59 Bangkok for the sprint week `offset` weeks from this one."""
    today = timezone.now().astimezone(SPRINT_TZ).date()
    monday = today - dt.timedelta(days=today.weekday()) + dt.timedelta(weeks=offset)
    start = dt.datetime.combine(monday, dt.time.min, tzinfo=SPRINT_TZ)
    return start, start + dt.timedelta(days=7) - dt.timedelta(seconds=1)


def make_project(workspace, user, identifier="AAA"):
    project = Project.objects.create(name=identifier, identifier=identifier, workspace=workspace, created_by=user)
    ProjectMember.objects.create(project=project, member=user, workspace=workspace, role=20)
    states = {
        "backlog": State.objects.create(name="Backlog", group="backlog", project=project, sequence=1),
        "todo": State.objects.create(name="Todo", group="unstarted", project=project, sequence=2),
        "progress": State.objects.create(name="In Progress", group="started", project=project, sequence=3),
        "done": State.objects.create(name="Done", group="completed", project=project, sequence=4),
        "cancelled": State.objects.create(name="Cancelled", group="cancelled", project=project, sequence=5),
    }
    estimate = Estimate.objects.create(name="Points", type="points", project=project)
    points = {
        value: EstimatePoint.objects.create(estimate=estimate, key=index, value=value, project=project)
        for index, value in enumerate(["1", "2", "4", "8"])
    }
    return project, states, points


def make_cycle(project, user, offset, name=None):
    start, end = week_bounds(offset)
    return Cycle.objects.create(
        name=name or f"Sprint {offset}", project=project, start_date=start, end_date=end, owned_by=user
    )


def make_story(project, user, state, point=None, cycle=None, epic=False, completed_at=None, created_at=None):
    issue_type = (
        IssueType.objects.create(workspace=project.workspace, name="Epic", is_epic=True) if epic else None
    )
    issue = Issue(
        name="story",
        project=project,
        workspace=project.workspace,
        state=state,
        estimate_point=point,
        type=issue_type,
    )
    issue.save(created_by_id=user.id)
    updates = {}
    if completed_at is not None:
        updates["completed_at"] = completed_at
    if created_at is not None:
        updates["created_at"] = created_at
    if updates:
        Issue.objects.filter(pk=issue.pk).update(**updates)
    if cycle is not None:
        CycleIssue.objects.create(issue=issue, cycle=cycle, project=project, workspace=project.workspace)
    return issue


def add_state_activity(project, issue, new_state, old_state, occurred_at, user):
    activity = IssueActivity.objects.create(
        issue=issue, project=project, workspace=project.workspace, verb="updated", field="state",
        old_identifier=old_state.id, new_identifier=new_state.id, actor=user,
    )
    IssueActivity.objects.filter(pk=activity.pk).update(created_at=occurred_at)
    return activity


def momentum_url(workspace):
    return f"/api/workspaces/{workspace.slug}/advance-analytics/"


def charts_url(workspace):
    return f"/api/workspaces/{workspace.slug}/advance-analytics-charts/"


@pytest.mark.contract
class TestMomentumAnalytics:
    @pytest.mark.django_db
    def test_velocity_series(self, session_client, workspace, create_user):
        project, states, points = make_project(workspace, create_user)
        last_week = make_cycle(project, create_user, -1)
        this_week = make_cycle(project, create_user, 0)
        last_start, _ = week_bounds(-1)
        this_start, _ = week_bounds(0)

        # completed last week, 4 points, committed to last week's cycle
        make_story(
            project, create_user, states["done"], points["4"], cycle=last_week,
            completed_at=last_start + dt.timedelta(hours=12),
        )
        # cancelled: excluded from committed and completed
        make_story(project, create_user, states["cancelled"], points["8"], cycle=last_week)
        # committed to this week's cycle, 2 points, not done yet
        make_story(project, create_user, states["todo"], points["2"], cycle=this_week)
        # completed this week with no cycle: counts toward completed points only
        make_story(
            project, create_user, states["done"], points["1"],
            completed_at=this_start + dt.timedelta(hours=12),
        )

        response = session_client.get(momentum_url(workspace), {"tab": "momentum", "weeks": 3})
        assert response.status_code == status.HTTP_200_OK, response.data

        chart = session_client.get(charts_url(workspace), {"type": "velocity", "weeks": 3})
        assert chart.status_code == status.HTTP_200_OK, chart.data
        data = chart.data["data"]
        assert len(data) == 3
        # current (incomplete) week is present and last
        assert data[-1]["key"] == f"{this_start.date().isocalendar().year}-W{this_start.date().isocalendar().week:02d}"
        # zero-filled first week
        assert (data[0]["committed_points"], data[0]["completed_points"]) == (0.0, 0.0)
        # cancelled story excluded: 4 committed, not 12
        assert (data[1]["committed_points"], data[1]["completed_points"]) == (4.0, 4.0)
        assert (data[2]["committed_points"], data[2]["completed_points"]) == (2.0, 1.0)
        # rolling average is null for the first two rows, then the 3-week mean
        assert data[0]["rolling_avg"] is None
        assert data[1]["rolling_avg"] is None
        assert data[2]["rolling_avg"] == 1.7

    @pytest.mark.django_db
    def test_throughput_counts_story_outside_cycle(self, session_client, workspace, create_user):
        project, states, points = make_project(workspace, create_user)
        this_start, _ = week_bounds(0)
        # done, not a member of any cycle
        make_story(
            project, create_user, states["done"], points["2"],
            completed_at=this_start + dt.timedelta(hours=9),
        )
        make_story(
            project, create_user, states["todo"], points["4"],
            cycle=make_cycle(project, create_user, 0),
        )

        response = session_client.get(charts_url(workspace), {"type": "throughput", "weeks": 1})
        assert response.status_code == status.HTTP_200_OK, response.data
        assert [row["completed_count"] for row in response.data["data"]] == [1]

    @pytest.mark.django_db
    def test_tiles_reliability_uses_last_elapsed_week(self, session_client, workspace, create_user):
        project, states, points = make_project(workspace, create_user)
        last_week = make_cycle(project, create_user, -1)
        this_week = make_cycle(project, create_user, 0)
        last_start, _ = week_bounds(-1)
        this_start, _ = week_bounds(0)

        # last elapsed week: 4 committed, 2 completed => 50%
        make_story(
            project, create_user, states["done"], points["2"], cycle=last_week,
            completed_at=last_start + dt.timedelta(hours=8),
        )
        make_story(project, create_user, states["todo"], points["2"], cycle=last_week)
        # current week numbers must not leak into reliability
        make_story(
            project, create_user, states["done"], points["8"], cycle=this_week,
            completed_at=this_start + dt.timedelta(hours=8),
        )

        response = session_client.get(momentum_url(workspace), {"tab": "momentum", "weeks": 2})
        assert response.status_code == status.HTTP_200_OK, response.data
        assert response.data["commitment_reliability"]["count"] == 50
        assert response.data["last_sprint_velocity"]["count"] == 2.0

        # a project with no committed work reports null, not a division error
        other, other_states, other_points = make_project(workspace, create_user, "BBB")
        make_story(
            other, create_user, other_states["done"], other_points["1"],
            completed_at=this_start + dt.timedelta(hours=1),
        )
        response = session_client.get(momentum_url(workspace), {"tab": "momentum", "weeks": 2,
                                                                "project_ids": str(other.id)})
        assert response.status_code == status.HTTP_200_OK, response.data
        assert response.data["commitment_reliability"]["count"] is None

    @pytest.mark.django_db
    def test_tiles_cycle_and_lead_time_percentiles(self, session_client, workspace, create_user):
        project, states, _points = make_project(workspace, create_user)
        this_start, _ = week_bounds(0)
        completed_at = this_start + dt.timedelta(days=1, hours=10)

        cycle_times = [1.0, 2.0, 3.0, 4.0]
        lead_times = [3.0, 4.0, 5.0, 6.0]
        for cycle_days, lead_days in zip(cycle_times, lead_times):
            story = make_story(
                project, create_user, states["done"],
                created_at=completed_at - dt.timedelta(days=lead_days),
                completed_at=completed_at,
            )
            add_state_activity(
                project, story, states["progress"], states["backlog"],
                completed_at - dt.timedelta(days=cycle_days), create_user,
            )
        # no started transition: cycle time falls back to created_at (5 days)
        make_story(
            project, create_user, states["done"],
            created_at=completed_at - dt.timedelta(days=5),
            completed_at=completed_at,
        )
        cycle_times.append(5.0)
        lead_times.append(5.0)

        response = session_client.get(momentum_url(workspace), {"tab": "momentum", "weeks": 2})
        assert response.status_code == status.HTTP_200_OK, response.data
        assert response.data["median_cycle_time"]["count"] == round(statistics.median(cycle_times), 1)
        assert response.data["p85_cycle_time"]["count"] == round(
            statistics.quantiles(cycle_times, n=20)[16], 1
        )
        assert response.data["median_lead_time"]["count"] == round(statistics.median(lead_times), 1)
        assert response.data["p85_lead_time"]["count"] == round(statistics.quantiles(lead_times, n=20)[16], 1)

        # cycle-time histogram buckets the same values, unrounded
        histogram = session_client.get(charts_url(workspace), {"type": "cycle-time", "weeks": 2})
        assert histogram.status_code == status.HTTP_200_OK, histogram.data
        counts = {row["key"]: row["count"] for row in histogram.data["data"]}
        assert counts == {"le_1d": 1, "d2_3": 2, "d4_7": 2, "d8_14": 0, "gt_14": 0}

    @pytest.mark.django_db
    def test_cycle_time_falls_back_to_created_at(self, session_client, workspace, create_user):
        project, states, _points = make_project(workspace, create_user)
        this_start, _ = week_bounds(0)
        completed_at = this_start + dt.timedelta(days=1, hours=10)
        make_story(
            project, create_user, states["done"],
            created_at=completed_at - dt.timedelta(days=5),
            completed_at=completed_at,
        )
        response = session_client.get(momentum_url(workspace), {"tab": "momentum", "weeks": 2})
        assert response.status_code == status.HTTP_200_OK, response.data
        assert response.data["median_cycle_time"]["count"] == 5.0
        assert response.data["median_lead_time"]["count"] == 5.0

    @pytest.mark.django_db
    def test_cumulative_flow_buckets_and_cancellation(self, session_client, workspace, create_user):
        project, states, _points = make_project(workspace, create_user)
        today = timezone.now().astimezone(SPRINT_TZ).date()
        day0, day1, day2 = today - dt.timedelta(days=2), today - dt.timedelta(days=1), today

        def at(day, hour):
            return dt.datetime.combine(day, dt.time(hour=hour), tzinfo=SPRINT_TZ)

        # backlog -> started -> completed across three days
        moved = make_story(project, create_user, states["done"], created_at=at(day0, 9))
        add_state_activity(project, moved, states["progress"], states["backlog"], at(day1, 10), create_user)
        add_state_activity(project, moved, states["done"], states["progress"], at(day2, 11), create_user)

        # created in backlog, cancelled on day 1: drops out from that day
        dropped = make_story(project, create_user, states["cancelled"], created_at=at(day0, 8))
        add_state_activity(project, dropped, states["cancelled"], states["backlog"], at(day1, 9), create_user)

        response = session_client.get(charts_url(workspace), {"type": "cumulative-flow", "days": 3})
        assert response.status_code == status.HTTP_200_OK, response.data
        data = response.data["data"]
        assert len(data) == 3
        assert data[0]["key"] == day0.isoformat()
        assert data[-1]["key"] == day2.isoformat()
        assert (data[0]["backlog"], data[0]["started"], data[0]["completed"]) == (2, 0, 0)
        assert (data[1]["backlog"], data[1]["started"], data[1]["completed"]) == (0, 1, 0)
        assert (data[2]["backlog"], data[2]["started"], data[2]["completed"]) == (0, 0, 1)

    @pytest.mark.django_db
    def test_epics_excluded_and_project_filter(self, session_client, workspace, create_user):
        project, states, points = make_project(workspace, create_user, "AAA")
        other, other_states, other_points = make_project(workspace, create_user, "BBB")
        this_start, _ = week_bounds(0)
        completed_at = this_start + dt.timedelta(hours=6)

        make_story(project, create_user, states["done"], points["2"], completed_at=completed_at)
        make_story(project, create_user, states["done"], points["4"], completed_at=completed_at, epic=True)
        make_story(other, create_user, other_states["done"], other_points["8"], completed_at=completed_at)

        # epics never count; both projects otherwise have one story each
        response = session_client.get(charts_url(workspace), {"type": "throughput", "weeks": 1})
        assert response.status_code == status.HTTP_200_OK, response.data
        assert [row["completed_count"] for row in response.data["data"]] == [2]

        # project_ids scopes to one project
        scoped = session_client.get(
            charts_url(workspace), {"type": "throughput", "weeks": 1, "project_ids": str(project.id)}
        )
        assert scoped.status_code == status.HTTP_200_OK, scoped.data
        assert [row["completed_count"] for row in scoped.data["data"]] == [1]

        # tiles are scoped too: one project => 2 completed points only
        tiles = session_client.get(
            momentum_url(workspace), {"tab": "momentum", "weeks": 2, "project_ids": str(project.id)}
        )
        assert tiles.status_code == status.HTTP_200_OK, tiles.data
        assert tiles.data["last_sprint_velocity"]["count"] == 0.0

    @pytest.mark.django_db
    def test_invalid_params_return_400(self, session_client, workspace, create_user):
        make_project(workspace, create_user)
        assert session_client.get(momentum_url(workspace), {"tab": "bogus"}).status_code == (
            status.HTTP_400_BAD_REQUEST
        )
        assert session_client.get(momentum_url(workspace), {"tab": "momentum", "weeks": 99}).status_code == (
            status.HTTP_400_BAD_REQUEST
        )
        assert session_client.get(charts_url(workspace), {"type": "velocity", "weeks": 99}).status_code == (
            status.HTTP_400_BAD_REQUEST
        )
        assert session_client.get(charts_url(workspace), {"type": "cumulative-flow", "days": 999}).status_code == (
            status.HTTP_400_BAD_REQUEST
        )
        assert session_client.get(charts_url(workspace), {"type": "bogus"}).status_code == (
            status.HTTP_400_BAD_REQUEST
        )

    def test_requires_login(self, api_client, workspace):
        assert api_client.get(momentum_url(workspace), {"tab": "momentum"}).status_code in (
            status.HTTP_401_UNAUTHORIZED,
            status.HTTP_403_FORBIDDEN,
        )
