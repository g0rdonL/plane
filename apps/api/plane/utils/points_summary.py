# Django imports
from django.db.models import Case, FloatField, Sum, Value, When
from django.db.models.functions import Cast

# Module imports
from plane.db.models import Issue


def points_summary(issue_queryset):
    """Todo / In progress / Done story point sums for a filtered work item queryset (aight fork).

    Sums over distinct ids so joins used for filtering or permissions cannot double count.
    """

    def group_sum(group):
        return Sum(Case(When(state__group=group, then="points"), default=Value(0.0), output_field=FloatField()))

    totals = (
        Issue.issue_objects.filter(
            id__in=issue_queryset.values("id"),
            estimate_point__estimate__type="points",
        )
        .annotate(points=Cast("estimate_point__value", FloatField()))
        .aggregate(
            unstarted_estimate_points=group_sum("unstarted"),
            started_estimate_points=group_sum("started"),
            completed_estimate_points=group_sum("completed"),
        )
    )
    return {k: v or 0 for k, v in totals.items()}
