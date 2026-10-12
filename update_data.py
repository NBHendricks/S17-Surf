import json
import os
import urllib.request
import urllib.parse

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo


PACIFIC = ZoneInfo("America/Los_Angeles")

# Ocean location just offshore from Campus Point
CAMPUS_LAT = 34.39
CAMPUS_LON = -119.85

SATELLITE_URL = (
    "https://coastwatch.pfeg.noaa.gov/erddap/"
    "griddap/jplMURSST41.json"
)


# ----------------------------------------
# DOWNLOAD INFORMATION
# ----------------------------------------

def download_text(url):

    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "S17-Surf/1.0"
        }
    )

    with urllib.request.urlopen(
        request,
        timeout=40
    ) as response:

        return response.read().decode(
            "utf-8",
            errors="replace"
        )


def download_json(url):

    return json.loads(download_text(url))


# ----------------------------------------
# NOAA BUOY DATA
# ----------------------------------------

def buoy_rows(station):

    url = (
        "https://www.ndbc.noaa.gov/"
        f"data/realtime2/{station}.txt"
    )

    lines = download_text(url).splitlines()

    if len(lines) < 3:
        raise RuntimeError(
            f"No buoy observations for {station}"
        )

    headers = lines[0].lstrip("#").split()

    rows = []

    for line in lines[2:]:

        values = line.split()

        if len(values) < len(headers):
            continue

        row = dict(zip(headers, values))

        try:
            observed = datetime(
                int(row["YY"]),
                int(row["MM"]),
                int(row["DD"]),
                int(row["hh"]),
                int(row["mm"]),
                tzinfo=timezone.utc
            )

        except (KeyError, ValueError):
            continue

        row["_observed"] = observed
        rows.append(row)

    return rows


def number(value):

    if value is None:
        return None

    if str(value) in {
        "MM",
        "999",
        "999.0",
        "99.0",
        "9999",
        "9999.0"
    }:
        return None

    try:
        return float(value)

    except (ValueError, TypeError):
        return None


def latest_value(rows, field, max_age_hours=6):

    cutoff = (
        datetime.now(timezone.utc)
        - timedelta(hours=max_age_hours)
    )

    for row in rows:

        if row["_observed"] < cutoff:
            continue

        value = number(row.get(field))

        if value is not None:
            return value

    return None


def feet(meters):

    if meters is None:
        return None

    return round(meters * 3.28084, 1)


def fahrenheit(celsius):

    if celsius is None:
        return None

    return round(celsius * 9 / 5 + 32, 1)


# ----------------------------------------
# HARVEST BUOY
# ----------------------------------------

def harvest_data():

    rows = buoy_rows("46218")

    return {
        "station": "46218",

        "wave_height_ft": feet(
            latest_value(rows, "WVHT")
        ),

        "period_sec": latest_value(
            rows, "DPD"
        ),

        "direction_deg": latest_value(
            rows, "MWD"
        )
    }


# ----------------------------------------
# NASA SATELLITE WATER TEMPERATURE
# ----------------------------------------

def satellite_water_temperature():

    # Ask NOAA for the latest available
    # NASA MUR sea surface temperature
    # near Campus Point.

    query = (
        "analysed_sst"
        "[(last)]"
        f"[({CAMPUS_LAT})]"
        f"[({CAMPUS_LON})]"
    )

    url = SATELLITE_URL + "?" + urllib.parse.quote(
        query,
        safe="[]():-."
    )

    result = download_json(url)

    table = result.get("table", {})

    columns = table.get("columnNames", [])
    rows = table.get("rows", [])

    if not rows:
        raise RuntimeError(
            "No satellite temperature returned"
        )

    for row in rows:

        observation = dict(zip(columns, row))

        temp_c = number(
            observation.get("analysed_sst")
        )

        if temp_c is None:
            continue

        # Basic check against invalid ocean temperatures
        if not -2 <= temp_c <= 40:
            continue

        observation_time = observation.get(
            "time", ""
        )

        if not observation_time:
            continue

        observed = datetime.fromisoformat(
            observation_time.replace("Z", "+00:00")
        )

        age = (
            datetime.now(timezone.utc) - observed
        ).total_seconds() / 3600

        # Do not present old satellite data
        # as a current temperature.
        if age < -24 or age > 120:
            raise RuntimeError(
                "Satellite temperature is too old"
            )

        return {
            "station": "NASA MUR",
            "temp_f": fahrenheit(temp_c),
            "source": "NASA satellite estimate",
            "observed": observation_time
        }

    raise RuntimeError(
        "No valid satellite temperature"
    )


# ----------------------------------------
# BACKUP WATER TEMPERATURE BUOYS
# ----------------------------------------

def buoy_water_temperature():

    for station in ["46053", "46251"]:

        try:

            rows = buoy_rows(station)

            temp_c = latest_value(
                rows,
                "WTMP",
                max_age_hours=24
            )

            if temp_c is not None:

                return {
                    "station": station,
                    "temp_f": fahrenheit(temp_c),
                    "source": (
                        "NOAA buoy " + station
                    )
                }

        except Exception as error:

            print(
                f"Temperature buoy {station} error:",
                error
            )

    return None


# ----------------------------------------
# CHOOSE WATER TEMPERATURE
# ----------------------------------------

def water_temperature():

    try:

        satellite = satellite_water_temperature()

        if satellite["temp_f"] is not None:

            print(
                "Using NASA satellite temperature:",
                satellite["temp_f"]
            )

            return satellite

    except Exception as error:

        print(
            "Satellite temperature error:",
            error
        )

    backup = buoy_water_temperature()

    if backup is not None:

        print(
            "Using backup buoy temperature:",
            backup["temp_f"]
        )

        return backup

    return {
        "station": None,
        "temp_f": None,
        "source": "Unavailable"
    }


# ----------------------------------------
# SANTA BARBARA TIDES
# ----------------------------------------

def tide_data(today):

    date_string = today.strftime("%Y%m%d")

    params = {
        "product": "predictions",
        "application": "S17-Surf",
        "begin_date": date_string,
        "end_date": date_string,
        "datum": "MLLW",
        "station": "9411340",
        "time_zone": "lst_ldt",
        "units": "english",
        "interval": "hilo",
        "format": "json"
    }

    url = (
        "https://api.tidesandcurrents.noaa.gov/"
        "api/prod/datagetter?"
        + urllib.parse.urlencode(params)
    )

    result = download_json(url)

    tides = []

    for item in result.get("predictions", []):

        timestamp = datetime.strptime(
            item["t"],
            "%Y-%m-%d %H:%M"
        )

        tides.append({
            "type": (
                "HIGH"
                if item["type"] == "H"
                else "LOW"
            ),

            "time": timestamp.strftime(
                "%-I:%M %p"
            ),

            "height_ft": round(
                float(item["v"]),
                1
            )
        })

    return tides


# ----------------------------------------
# CAMPUS POINT YOUTUBE CAMERA
# ----------------------------------------

def campus_live_cam():

    # Your confirmed Campus Point video.
    # The website embeds this same video directly.

    return {
        "video_id": "sVENjHlL4Pk",
        "title": "Campus Point Surf Cam"
    }


# ----------------------------------------
# MAIN UPDATE
# ----------------------------------------

def main():

    now = datetime.now(PACIFIC)

    data = {
        "date_display": now.strftime(
            "%A, %B %-d, %Y"
        ),

        "updated_display": now.strftime(
            "%-I:%M %p %Z"
        ),

        "harvest": None,

        "water_temp": None,

        "tides": [],

        "campus_cam": campus_live_cam()
    }

    try:
        data["harvest"] = harvest_data()

    except Exception as error:
        print("Harvest error:", error)

    try:
        data["water_temp"] = water_temperature()

    except Exception as error:
        print("Water temperature error:", error)

    try:
        data["tides"] = tide_data(now)

    except Exception as error:
        print("Tides error:", error)

    with open(
        "data.json",
        "w",
        encoding="utf-8"
    ) as file:

        json.dump(
            data,
            file,
            indent=2
        )

    print(json.dumps(data, indent=2))


if __name__ == "__main__":
    main()
