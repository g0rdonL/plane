# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

from rest_framework import serializers

from plane.db.models import IssueRecurrence
from plane.utils.recurrence import FREQUENCIES


class IssueRecurrenceSerializer(serializers.ModelSerializer):
    frequency = serializers.ChoiceField(choices=FREQUENCIES)
    weekdays = serializers.ListField(
        child=serializers.IntegerField(min_value=0, max_value=6), required=False, default=list
    )
    day_of_month = serializers.IntegerField(min_value=1, max_value=31, required=False, allow_null=True, default=None)

    class Meta:
        model = IssueRecurrence
        fields = ["frequency", "weekdays", "day_of_month", "next_run_at", "is_active"]
        read_only_fields = ["next_run_at", "is_active"]

    def validate(self, attrs):
        frequency = attrs["frequency"]
        weekdays = sorted(set(attrs.get("weekdays") or []))
        day_of_month = attrs.get("day_of_month")
        if frequency == "weekly" and not weekdays:
            raise serializers.ValidationError({"weekdays": "Pick at least one day."})
        if frequency != "weekly" and weekdays:
            raise serializers.ValidationError({"weekdays": "Only weekly repeats take days."})
        if frequency == "monthly" and day_of_month is None:
            raise serializers.ValidationError({"day_of_month": "Pick a day of the month."})
        if frequency != "monthly" and day_of_month is not None:
            raise serializers.ValidationError({"day_of_month": "Only monthly repeats take a day of the month."})
        attrs["weekdays"] = weekdays
        return attrs
