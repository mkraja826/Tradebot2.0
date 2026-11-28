"""Gold demo entry hours, using the NYSE calendar and the operator's IST weekend."""
from datetime import datetime
from zoneinfo import ZoneInfo

NEW_YORK = ZoneInfo("America/New_York")
INDIA = ZoneInfo("Asia/Kolkata")

# Published NYSE calendar: https://www.nyse.com/markets/hours-calendars
HOLIDAYS = {
    2026: {"01-01", "01-19", "02-16", "04-03", "05-25", "06-19", "07-03", "09-07", "11-26", "12-25"},
    2027: {"01-01", "01-18", "02-15", "03-26", "05-31", "06-18", "07-05", "09-06", "11-25", "12-24"},
    2028: {"01-17", "02-21", "04-14", "05-29", "06-19", "07-04", "09-04", "11-23", "12-25"},
}
EARLY_CLOSES = {"2026-11-27", "2026-12-24", "2027-11-26", "2028-07-03", "2028-11-24"}


def entry_pause_reason(timestamp):
    local = datetime.fromtimestamp(timestamp, NEW_YORK)
    if local.astimezone(INDIA).weekday() >= 5 or local.weekday() >= 5:
        return "weekend"
    if local.year not in HOLIDAYS:
        return "calendar_update_required"
    if local.strftime("%m-%d") in HOLIDAYS[local.year]:
        return "nyse_holiday"
    close_hour = 13 if local.date().isoformat() in EARLY_CLOSES else 16
    if not 9 <= local.hour < close_hour:
        return "outside_nyse_entry_hours"
    return None
