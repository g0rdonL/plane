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
    IssueAssignee,
    IssueType,
    Project,
    ProjectMember,
    State,
    User,
    WorkspaceMember,
)
from plane.utils.sprint import SPRINT_TZ


def week_bounds(offset):
    """Monday 00:00 to Sunday 23:59:59 Bangkok for the sprint week `offset` weeks from this one."""
    today = timezone.now().astimezone(SPRINT_TZ).date()
    monday = today - dt.timedelta(days=today.weekday()) + dt.timedelta(weeks=offset)
    start = dt.datetime.combine(monday, dt.time.min, tzinfo=SPRINT_TZ)
    return start, start + dt.timedelta(days=7) - dt.timedelta(seconds=1)


def week_key(start):
    iso = start.date().isocalendar()
    return f"{iso.year}-W{iso.week:02d}"


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


def make_teammate(workspace, project, email="teammate@plane.so"):
    """A second workspace + project member used as the other story assignee."""
    user = User.objects.create(email=email, username=email.split("@")[0], first_name="Team", last_name="Mate")
    WorkspaceMember.objects.create(workspace=workspace, member=user, role=15)
    ProjectMember.objects.create(project=project, member=user, workspace=workspace, role=15)
    return user


def assign_story(issue, user):
    return IssueAssignee.objects.create(
        issue=issue, assignee=user, project=issue.project, workspace=issue.workspace
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


def add_cycle_activity(project, issue, verb, occurred_at, user, old_cycle=None, new_cycle=None):
    activity = IssueActivity.objects.create(
        issue=issue, project=project, workspace=project.workspace, verb=verb, field="cycles",
        old_identifier=old_cycle.id if old_cycle is not None else None,
        new_identifier=new_cycle.id if new_cycle is not None else None, actor=user,
    )
    IssueActivity.objects.filter(pk=activity.pk).update(created_at=occurred_at)
    return activity


def add_estimate_activity(project, issue, occurred_at, user, field="estimate_points"):
    activity = IssueActivity.objects.create(
        issue=issue, project=project, workspace=project.workspace, verb="updated", field=field, actor=user,
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
    def test_estimate_accuracy_groups_by_points(self, session_client, workspace, create_user):
        project, states, points = make_project(workspace, create_user)
        this_start, _ = week_bounds(0)
        completed_at = this_start + dt.timedelta(hours=6)

        def completed_story(point, cycle_days, started=True):
            story = make_story(
                project, create_user, states["done"], point,
                created_at=completed_at - dt.timedelta(days=cycle_days),
                completed_at=completed_at,
            )
            if started:
                add_state_activity(
                    project, story, states["progress"], states["backlog"],
                    completed_at - dt.timedelta(days=cycle_days), create_user,
                )
            return story

        # 1 point: cycles 1.0 and 2.0
        story_a = completed_story(points["1"], 1.0)
        completed_story(points["1"], 2.0)
        # 2 points: cycle 4.0, re-estimated after it started
        story_c = completed_story(points["2"], 4.0)
        add_estimate_activity(project, story_c, completed_at - dt.timedelta(days=2), create_user)
        # 4 points: cycles 6.0, 8.0 and 10.0 (fallback to created_at, no started transition)
        completed_story(points["4"], 6.0)
        completed_story(points["4"], 8.0)
        completed_story(points["4"], 10.0, started=False)
        # estimate changed BEFORE the story started: must not count as re-estimated
        add_estimate_activity(project, story_a, completed_at - dt.timedelta(days=3), create_user)
        # no estimate: counted separately, never grouped
        make_story(project, create_user, states["done"], completed_at=completed_at)
        # an epic with points is excluded entirely
        make_story(project, create_user, states["done"], points["8"], completed_at=completed_at, epic=True)

        response = session_client.get(charts_url(workspace), {"type": "estimate-accuracy", "weeks": 2})
        assert response.status_code == status.HTTP_200_OK, response.data
        data = response.data["data"]
        assert [row["key"] for row in data] == ["1", "2", "4"]
        assert response.data["unestimated_count"] == 1

        by_key = {row["key"]: row for row in data}
        assert by_key["1"]["count"] == 2
        assert by_key["1"]["median_days"] == 1.5
        assert by_key["1"]["p85_days"] == round(statistics.quantiles([1.0, 2.0], n=20)[16], 1)
        assert by_key["1"]["min_days"] == 1.0
        assert by_key["1"]["max_days"] == 2.0
        assert by_key["1"]["reestimated_count"] == 0
        assert by_key["1"]["name"] == "1 pts"

        assert by_key["2"]["count"] == 1
        assert by_key["2"]["median_days"] == 4.0
        assert by_key["2"]["p85_days"] == 4.0
        assert by_key["2"]["reestimated_count"] == 1

        assert by_key["4"]["count"] == 3
        assert by_key["4"]["median_days"] == 8.0
        assert by_key["4"]["p85_days"] == round(statistics.quantiles([6.0, 8.0, 10.0], n=20)[16], 1)
        assert by_key["4"]["min_days"] == 6.0
        assert by_key["4"]["max_days"] == 10.0

    @pytest.mark.django_db
    def test_estimate_accuracy_invalid_weeks(self, session_client, workspace, create_user):
        make_project(workspace, create_user)
        assert session_client.get(
            charts_url(workspace), {"type": "estimate-accuracy", "weeks": 99}
        ).status_code == status.HTTP_400_BAD_REQUEST

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

    @pytest.mark.django_db
    def test_carryover_story_moved_to_next_cycle_counts_in_both(self, session_client, workspace, create_user):
        project, states, points = make_project(workspace, create_user)
        last_week = make_cycle(project, create_user, -1)
        this_week = make_cycle(project, create_user, 0)
        last_start, _ = week_bounds(-1)
        this_start, _ = week_bounds(0)

        story = make_story(project, create_user, states["todo"], points["4"], cycle=last_week)
        add_cycle_activity(
            project, story, "created", last_start + dt.timedelta(hours=1), create_user, new_cycle=last_week
        )
        # carried over into this week's cycle after last week closed (CycleIssue row overwritten in place)
        add_cycle_activity(
            project, story, "updated", this_start + dt.timedelta(hours=1), create_user,
            old_cycle=last_week, new_cycle=this_week,
        )
        CycleIssue.objects.filter(issue=story, cycle=last_week).update(cycle=this_week)

        chart = session_client.get(charts_url(workspace), {"type": "carryover", "weeks": 3})
        assert chart.status_code == status.HTTP_200_OK, chart.data
        rows = {row["key"]: row for row in chart.data["data"]}
        assert rows[week_key(last_start)]["committed_points"] == 4.0
        assert rows[week_key(last_start)]["carryover_points"] == 4.0
        assert rows[week_key(last_start)]["carryover_count"] == 1
        # and it is committed to this week's cycle too
        assert rows[week_key(this_start)]["committed_points"] == 4.0

    @pytest.mark.django_db
    def test_carryover_excludes_story_completed_before_close(self, session_client, workspace, create_user):
        project, states, points = make_project(workspace, create_user)
        last_week = make_cycle(project, create_user, -1)
        last_start, _ = week_bounds(-1)
        make_story(
            project, create_user, states["done"], points["4"], cycle=last_week,
            completed_at=last_start + dt.timedelta(hours=12),
        )

        chart = session_client.get(charts_url(workspace), {"type": "carryover", "weeks": 2})
        assert chart.status_code == status.HTTP_200_OK, chart.data
        row = {r["key"]: r for r in chart.data["data"]}[week_key(last_start)]
        assert row["committed_points"] == 4.0
        assert row["carryover_points"] == 0.0
        assert row["carryover_count"] == 0

    @pytest.mark.django_db
    def test_carryover_excludes_story_removed_before_close(self, session_client, workspace, create_user):
        project, states, points = make_project(workspace, create_user)
        last_week = make_cycle(project, create_user, -1)
        last_start, _ = week_bounds(-1)
        story = make_story(project, create_user, states["todo"], points["4"], cycle=last_week)
        add_cycle_activity(
            project, story, "created", last_start + dt.timedelta(hours=1), create_user, new_cycle=last_week
        )
        add_cycle_activity(
            project, story, "deleted", last_start + dt.timedelta(days=2), create_user, old_cycle=last_week
        )
        CycleIssue.objects.filter(issue=story, cycle=last_week).delete()

        chart = session_client.get(charts_url(workspace), {"type": "carryover", "weeks": 2})
        assert chart.status_code == status.HTTP_200_OK, chart.data
        row = {r["key"]: r for r in chart.data["data"]}[week_key(last_start)]
        assert row["committed_points"] == 0.0
        assert row["carryover_points"] == 0.0
        assert row["carryover_count"] == 0

    @pytest.mark.django_db
    def test_carryover_excludes_story_added_after_close(self, session_client, workspace, create_user):
        project, states, points = make_project(workspace, create_user)
        last_week = make_cycle(project, create_user, -1)
        this_start, _ = week_bounds(0)
        story = make_story(project, create_user, states["todo"], points["4"], cycle=last_week)
        # only added to last week's cycle after it had already closed
        add_cycle_activity(
            project, story, "created", this_start + dt.timedelta(hours=1), create_user, new_cycle=last_week
        )

        chart = session_client.get(charts_url(workspace), {"type": "carryover", "weeks": 2})
        assert chart.status_code == status.HTTP_200_OK, chart.data
        row = {r["key"]: r for r in chart.data["data"]}[week_key(this_start - dt.timedelta(days=7))]
        assert row["committed_points"] == 0.0
        assert row["carryover_count"] == 0

    @pytest.mark.django_db
    def test_carryover_chart_shape_and_rate(self, session_client, workspace, create_user):
        project, states, points = make_project(workspace, create_user)
        last_week = make_cycle(project, create_user, -1)
        last_start, _ = week_bounds(-1)
        # completed before close: committed, not carryover
        make_story(
            project, create_user, states["done"], points["4"], cycle=last_week,
            completed_at=last_start + dt.timedelta(hours=6),
        )
        # unfinished: committed and carryover
        make_story(project, create_user, states["todo"], points["4"], cycle=last_week)

        chart = session_client.get(charts_url(workspace), {"type": "carryover", "weeks": 2})
        assert chart.status_code == status.HTTP_200_OK, chart.data
        rows = {row["key"]: row for row in chart.data["data"]}
        row = rows[week_key(last_start)]
        assert {
            "key", "name", "committed_points", "carryover_points", "carryover_count", "carryover_rate",
        } <= set(row)
        assert (row["committed_points"], row["carryover_points"], row["carryover_count"]) == (8.0, 4.0, 1)
        assert row["carryover_rate"] == 50.0
        assert "carryover_rate" in chart.data["schema"]
        # a week with no committed work reports a zero rate, not a division error
        assert rows[week_key(last_start + dt.timedelta(days=7))]["carryover_rate"] == 0.0

        assert session_client.get(charts_url(workspace), {"type": "carryover", "weeks": 99}).status_code == (
            status.HTTP_400_BAD_REQUEST
        )

    @pytest.mark.django_db
    def test_momentum_carryover_tile(self, session_client, workspace, create_user):
        project, states, points = make_project(workspace, create_user)
        last_week = make_cycle(project, create_user, -1)
        last_start, _ = week_bounds(-1)
        make_story(
            project, create_user, states["done"], points["4"], cycle=last_week,
            completed_at=last_start + dt.timedelta(hours=6),
        )
        make_story(project, create_user, states["todo"], points["4"], cycle=last_week)

        response = session_client.get(momentum_url(workspace), {"tab": "momentum", "weeks": 3})
        assert response.status_code == status.HTTP_200_OK, response.data
        assert "carryover_rate" in response.data

        # weeks=3 → the two elapsed weeks (0% and 50%) are averaged; the running week is left out
        assert response.data["carryover_rate"]["count"] == 25.0

    @pytest.mark.django_db
    def test_carryover_zero_while_sprint_is_running(self, session_client, workspace, create_user):
        project, states, points = make_project(workspace, create_user)
        this_week = make_cycle(project, create_user, 0)
        this_start, _ = week_bounds(0)
        make_story(project, create_user, states["todo"], points["4"], cycle=this_week)

        chart = session_client.get(charts_url(workspace), {"type": "carryover", "weeks": 2})
        assert chart.status_code == status.HTTP_200_OK, chart.data
        row = {r["key"]: r for r in chart.data["data"]}[week_key(this_start)]
        assert (row["committed_points"], row["carryover_points"], row["carryover_count"]) == (4.0, 0.0, 0)

    @pytest.mark.django_db
    def test_carryover_respects_assignee_filter(self, session_client, workspace, create_user):
        project, states, points = make_project(workspace, create_user)
        teammate = make_teammate(workspace, project)
        last_week = make_cycle(project, create_user, -1)
        last_start, _ = week_bounds(-1)
        mine = make_story(project, create_user, states["todo"], points["4"], cycle=last_week)
        theirs = make_story(project, create_user, states["todo"], points["2"], cycle=last_week)
        assign_story(mine, create_user)
        assign_story(theirs, teammate)

        chart = session_client.get(
            charts_url(workspace), {"type": "carryover", "weeks": 2, "assignee_ids": str(teammate.id)}
        )
        assert chart.status_code == status.HTTP_200_OK, chart.data
        row = {r["key"]: r for r in chart.data["data"]}[week_key(last_start)]
        assert (row["committed_points"], row["carryover_points"], row["carryover_count"]) == (2.0, 2.0, 1)

        tiles = session_client.get(
            momentum_url(workspace), {"tab": "momentum", "weeks": 3, "assignee_ids": str(teammate.id)}
        )
        assert tiles.status_code == status.HTTP_200_OK, tiles.data

    def test_requires_login(self, api_client, workspace):
        assert api_client.get(momentum_url(workspace), {"tab": "momentum"}).status_code in (
            status.HTTP_401_UNAUTHORIZED,
            status.HTTP_403_FORBIDDEN,
        )


@pytest.mark.contract
class TestMomentumAssigneeFilter:
    """Aight fork: momentum can be scoped to one staff member via all[issue_assignee]."""

    @pytest.mark.django_db
    def test_assignee_filter_scopes_velocity_and_tiles(self, session_client, workspace, create_user):
        project, states, points = make_project(workspace, create_user)
        teammate = make_teammate(workspace, project)
        this_week = make_cycle(project, create_user, 0)
        this_start, _ = week_bounds(0)
        completed_at = this_start + dt.timedelta(hours=12)

        mine = make_story(project, create_user, states["done"], points["4"], cycle=this_week, completed_at=completed_at)
        assign_story(mine, create_user)
        theirs = make_story(
            project, create_user, states["done"], points["8"], cycle=this_week, completed_at=completed_at
        )
        assign_story(theirs, teammate)

        # without the filter both stories count
        unfiltered = session_client.get(charts_url(workspace), {"type": "velocity", "weeks": 1})
        assert unfiltered.status_code == status.HTTP_200_OK, unfiltered.data
        row = unfiltered.data["data"][-1]
        assert (row["committed_points"], row["completed_points"]) == (12.0, 12.0)

        # scoped to user1 only: committed/completed points drop to their 4
        scoped = session_client.get(
            charts_url(workspace), {"type": "velocity", "weeks": 1, "assignee_ids": str(create_user.id)}
        )
        assert scoped.status_code == status.HTTP_200_OK, scoped.data
        row = scoped.data["data"][-1]
        assert (row["committed_points"], row["completed_points"]) == (4.0, 4.0)

        # momentum tiles honour the filter too (weeks=1 => last sprint is the current week)
        tiles = session_client.get(momentum_url(workspace), {"tab": "momentum", "weeks": 1})
        assert tiles.status_code == status.HTTP_200_OK, tiles.data
        assert tiles.data["last_sprint_velocity"]["count"] == 12.0
        assert tiles.data["avg_throughput"]["count"] == 2.0

        scoped_tiles = session_client.get(
            momentum_url(workspace), {"tab": "momentum", "weeks": 1, "assignee_ids": str(create_user.id)}
        )
        assert scoped_tiles.status_code == status.HTTP_200_OK, scoped_tiles.data
        assert scoped_tiles.data["last_sprint_velocity"]["count"] == 4.0
        assert scoped_tiles.data["avg_throughput"]["count"] == 1.0

    @pytest.mark.django_db
    def test_assignee_filter_scopes_throughput_and_cycle_time(self, session_client, workspace, create_user):
        project, states, points = make_project(workspace, create_user)
        teammate = make_teammate(workspace, project)
        this_week = make_cycle(project, create_user, 0)
        this_start, _ = week_bounds(0)
        completed_at = this_start + dt.timedelta(days=1, hours=10)

        # user1: fast (≈1 day cycle time)
        mine = make_story(project, create_user, states["done"], points["2"], cycle=this_week, completed_at=completed_at)
        assign_story(mine, create_user)
        add_state_activity(
            project, mine, states["progress"], states["backlog"],
            completed_at - dt.timedelta(days=1), create_user,
        )
        # user2: slow (≈5 day cycle time)
        theirs = make_story(project, create_user, states["done"], points["2"], cycle=this_week, completed_at=completed_at)
        assign_story(theirs, teammate)
        add_state_activity(
            project, theirs, states["progress"], states["backlog"],
            completed_at - dt.timedelta(days=5), create_user,
        )

        unfiltered = session_client.get(charts_url(workspace), {"type": "throughput", "weeks": 1})
        assert [row["completed_count"] for row in unfiltered.data["data"]] == [2]
        scoped = session_client.get(
            charts_url(workspace), {"type": "throughput", "weeks": 1, "assignee_ids": str(create_user.id)}
        )
        assert [row["completed_count"] for row in scoped.data["data"]] == [1]

        unfiltered_histogram = session_client.get(charts_url(workspace), {"type": "cycle-time", "weeks": 2})
        counts = {row["key"]: row["count"] for row in unfiltered_histogram.data["data"]}
        assert counts["le_1d"] == 1
        assert counts["d4_7"] == 1
        scoped_histogram = session_client.get(
            charts_url(workspace), {"type": "cycle-time", "weeks": 2, "assignee_ids": str(create_user.id)}
        )
        scoped_counts = {row["key"]: row["count"] for row in scoped_histogram.data["data"]}
        assert scoped_counts == {"le_1d": 1, "d2_3": 0, "d4_7": 0, "d8_14": 0, "gt_14": 0}

    @pytest.mark.django_db
    def test_assignee_filter_scopes_cumulative_flow(self, session_client, workspace, create_user):
        project, states, _points = make_project(workspace, create_user)
        teammate = make_teammate(workspace, project)
        today = timezone.now().astimezone(SPRINT_TZ).date()
        created_at = dt.datetime.combine(today, dt.time(hour=9), tzinfo=SPRINT_TZ)

        mine = make_story(project, create_user, states["todo"], created_at=created_at)
        assign_story(mine, create_user)
        theirs = make_story(project, create_user, states["todo"], created_at=created_at)
        assign_story(theirs, teammate)

        unfiltered = session_client.get(charts_url(workspace), {"type": "cumulative-flow", "days": 1})
        assert unfiltered.data["data"][-1]["unstarted"] == 2
        scoped = session_client.get(
            charts_url(workspace), {"type": "cumulative-flow", "days": 1, "assignee_ids": str(create_user.id)}
        )
        assert scoped.status_code == status.HTTP_200_OK, scoped.data
        assert scoped.data["data"][-1]["unstarted"] == 1

    @pytest.mark.django_db
    def test_invalid_assignee_ids_return_400(self, session_client, workspace, create_user):
        make_project(workspace, create_user)
        assert session_client.get(
            momentum_url(workspace), {"tab": "momentum", "assignee_ids": "not-a-uuid"}
        ).status_code == status.HTTP_400_BAD_REQUEST
        assert session_client.get(
            charts_url(workspace), {"type": "velocity", "assignee_ids": "not-a-uuid"}
        ).status_code == status.HTTP_400_BAD_REQUEST
