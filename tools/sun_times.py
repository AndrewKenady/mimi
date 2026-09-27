"""Example MIMI community tool: sunrise, sunset and twilight, computed offline.

Uses the NOAA "sunrise equation" (accurate to about a minute outside the polar
regions). Times are shown in the device's time zone.
"""

import math
from datetime import date, datetime, timedelta, timezone

NAME = "sun_times"
DESCRIPTION = (
    "Sunrise, sunset, first/last light and day length for a date, at the current location "
    "or a named place. Use for questions like 'when is sunset?' or 'how much daylight is left?'."
)
PARAMETERS = {
    "type": "object",
    "properties": {
        "date": {"type": "string", "description": "'today' (default), 'tomorrow', or YYYY-MM-DD"},
        "place": {"type": "string", "description": "Optional place name; omit for the current location"},
    },
}
LABEL = "Checked sunrise and sunset"


def _julian_to_dt(j: float) -> datetime:
    return datetime.fromtimestamp((j - 2440587.5) * 86400, tz=timezone.utc)


def solar_events(day: date, lat: float, lon: float) -> dict:
    """UTC datetimes for dawn/sunrise/noon/sunset/dusk (None when the sun doesn't cross)."""
    n = day.toordinal() - date(2000, 1, 1).toordinal()
    j_star = n + 0.0009 - lon / 360.0
    m = math.radians((357.5291 + 0.98560028 * j_star) % 360)
    c = 1.9148 * math.sin(m) + 0.0200 * math.sin(2 * m) + 0.0003 * math.sin(3 * m)
    lam = math.radians((math.degrees(m) + c + 180 + 102.9372) % 360)
    transit = 2451545.0 + j_star + 0.0053 * math.sin(m) - 0.0069 * math.sin(2 * lam)
    dec = math.asin(math.sin(lam) * math.sin(math.radians(23.4397)))
    phi = math.radians(lat)

    def crossing(alt_deg: float):
        cos_w = (math.sin(math.radians(alt_deg)) - math.sin(phi) * math.sin(dec)) / (math.cos(phi) * math.cos(dec))
        if cos_w > 1:
            return "below"  # the sun stays below this altitude all day
        if cos_w < -1:
            return "above"  # ... or above it all day
        w = math.degrees(math.acos(cos_w)) / 360.0
        return _julian_to_dt(transit - w), _julian_to_dt(transit + w)

    out = {"noon": _julian_to_dt(transit)}
    for key, alt in (("sun", -0.833), ("civil", -6.0)):
        r = crossing(alt)
        out[key] = r
    return out


def _parse_day(s: str, today: date) -> date:
    s = (s or "today").strip().lower()
    if s in ("", "today", "now", "tonight"):
        return today
    if s == "tomorrow":
        return today + timedelta(days=1)
    if s == "yesterday":
        return today - timedelta(days=1)
    return date.fromisoformat(s)


def run(args: dict, ctx) -> dict:
    where = ctx.location
    if args.get("place"):
        where = ctx.find_place(args["place"]) or None
        if not where:
            return {"text": f"Couldn't find '{args['place']}' on the offline map."}
    if not where:
        return {"text": "The current location is unknown. Ask the user where they are, or which place they mean."}
    try:
        day = _parse_day(args.get("date", ""), ctx.now.date())
    except ValueError:
        return {"text": "The date should be 'today', 'tomorrow' or YYYY-MM-DD."}

    tz = ctx.now.tzinfo
    ev = solar_events(day, float(where["lat"]), float(where["lon"]))
    h24 = ctx.units == "metric"

    def t(d: datetime) -> str:
        d = d.astimezone(tz)
        return d.strftime("%H:%M") if h24 else d.strftime("%I:%M %p").lstrip("0")

    name = where.get("name") or f"{where['lat']:.3f}, {where['lon']:.3f}"
    head = f"{name}, {day.strftime('%A %d %B %Y')} (times in the device's time zone, {ctx.now.strftime('%Z') or 'local'}):"
    sun, civil = ev["sun"], ev["civil"]
    if sun == "above":
        return {"text": f"{head} the sun doesn't set (midnight sun). Solar noon {t(ev['noon'])}."}
    if sun == "below":
        return {"text": f"{head} the sun doesn't rise (polar night). Solar noon {t(ev['noon'])}."}
    length = sun[1] - sun[0]
    hrs, mins = divmod(round(length.total_seconds() / 60), 60)
    parts = [head]
    if isinstance(civil, tuple):
        parts.append(f"first light {t(civil[0])},")
    parts.append(f"sunrise {t(sun[0])}, solar noon {t(ev['noon'])}, sunset {t(sun[1])}")
    if isinstance(civil, tuple):
        parts[-1] += f", last light {t(civil[1])}"
    parts[-1] += "."
    parts.append(f"Day length {hrs} h {mins} min.")
    if day == ctx.now.date():
        left = sun[1] - ctx.now
        if timedelta(0) < left < length:
            lh, lm = divmod(round(left.total_seconds() / 60), 60)
            parts.append(f"Daylight left: {lh} h {lm} min." if lh else f"Daylight left: {lm} min.")
        elif left <= timedelta(0):
            parts.append("The sun has already set today.")
    return {"text": " ".join(parts), "data": {"place": name, "date": day.isoformat()}}
