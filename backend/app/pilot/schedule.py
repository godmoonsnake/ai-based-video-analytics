"""Schedules use the site's timezone and the observed timestamp, not arrival time."""

from datetime import datetime
from zoneinfo import ZoneInfo
from pydantic import BaseModel, Field, model_validator


class ZoneSchedule(BaseModel):
    # For overnight windows, weekdays refer to the day the window starts.
    weekdays: list[int] = Field(min_length=1, max_length=7)
    start: str = Field(pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    end: str = Field(pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    all_day: bool = False

    @model_validator(mode="after")
    def validate_days(self):
        if any(day < 0 or day > 6 for day in self.weekdays) or len(
            set(self.weekdays)
        ) != len(self.weekdays):
            raise ValueError(
                "weekdays must be unique integers from Monday=0 to Sunday=6"
            )
        if self.start == self.end and not self.all_day:
            raise ValueError("equal start/end requires all_day=true")
        return self


def active_at(schedule: dict, timestamp: float, timezone: str) -> bool:
    value = ZoneSchedule.model_validate(schedule)
    local = datetime.fromtimestamp(timestamp, ZoneInfo(timezone))
    if value.all_day:
        return local.weekday() in value.weekdays
    minute = local.strftime("%H:%M")
    if value.start < value.end:
        return local.weekday() in value.weekdays and value.start <= minute < value.end
    if minute >= value.start:
        return local.weekday() in value.weekdays
    return (local.weekday() - 1) % 7 in value.weekdays and minute < value.end
