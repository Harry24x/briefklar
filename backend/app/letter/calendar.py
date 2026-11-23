"""Turn a letter deadline into an .ics calendar file with reminders 7 days and 1 day before."""

from datetime import date, timedelta

from ics import Calendar, DisplayAlarm, Event

REMINDERS = (timedelta(days=-7), timedelta(days=-1))


def make_ics(deadline: date, title: str, notes: str = "") -> str:
    event = Event(name=title[:120], begin=deadline, description=notes[:1000])
    event.make_all_day()
    for trigger in REMINDERS:
        event.alarms.append(DisplayAlarm(trigger=trigger, display_text=title[:120]))
    calendar = Calendar()
    calendar.events.add(event)
    return calendar.serialize()
