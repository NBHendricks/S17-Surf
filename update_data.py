import json
import os
import urllib.request
import urllib.parse

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo


PACIFIC = ZoneInfo("America/Los_Angeles")


# ----------------------------------------
# DOWNLOAD INFORMATION
# ----------------------------------------

def download_text(url):

    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "S17-Surf/1.0 (surf dashboard)"
        }
    )

    with urllib.request.urlopen(
        request,
        timeout=30
    ) as response:

        return response.read().decode(
            "utf-8",
            errors="replace"
        )


def download_json(url):

    return json.loads(download_text(url))


# ----------------------------------------
# READ NOAA BUOY
# ----------------------------------------

def buoy_rows(station):

    url = (
        "https://www.ndbc.noaa.gov/"
        f"data/realtime2/{station}.txt"
    )

    lines = download_text(url).splitlines()

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

    if value in {
        "MM", "999", "999.0",
        "99.0", "9999", "9999.0"
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

    wave = latest_value(rows, "WVHT")
    period = latest_value(rows, "DPD")
    direction = latest_value(rows, "MWD")

    return {
        "station": "46218",
        "wave_height_ft": feet(wave),
        "period_sec": period,
        "direction_deg": direction
    }


# ----------------------------------------
# CAMPUS POINT AREA WATER TEMPERATURE
# ----------------------------------------
def water_temperature():

    for station in ["46053", "46251"]:

        try:
            rows = buoy_rows(station)

            water_c = latest_value(
                rows,
                "WTMP",
                max_age_hours=24
            )

            if water_c is not None:

                return {
                    "station": station,
                    "temp_f": fahrenheit(water_c)
                }

        except Exception as error:
            print(
                f"Water temperature error at {station}:",
                error
            )

    return {
        "station": None,
        "temp_f": None
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
            "time": timestamp.strftime("%-I:%M %p"),
            "height_ft": round(float(item["v"]), 1)
        })

    return tides


# ----------------------------------------
# LIVE CAMPUS POINT YOUTUBE CAMERA
# ----------------------------------------

def campus_live_cam():

    api_key = os.environ.get("YOUTUBE_API_KEY")

    if not api_key:
        print("YouTube API key not configured")
        return None

    params = {
        "part": "snippet",
        "q": "Campus Point Surf Cam GRIT",
        "type": "video",
        "eventType": "live",
        "videoEmbeddable": "true",
        "maxResults": "10",
        "key": api_key
    }

    url = (
        "https://www.googleapis.com/"
        "youtube/v3/search?"
        + urllib.parse.urlencode(params)
    )

    result = download_json(url)

    for item in result.get("items", []):

        snippet = item.get("snippet", {})

        title = snippet.get("title", "").lower()

        channel = snippet.get(
            "channelTitle", ""
        ).lower()

        video_id = item.get(
            "id", {}
        ).get("videoId")

        if (
            video_id
            and "campus point" in title
            and "grit" in channel
        ):

            return {
                "video_id": video_id,
                "title": snippet.get("title"),
                "channel": snippet.get("channelTitle")
            }

    print("No matching live Campus Point stream found")

    return None


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
        "campus_cam": None
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

    try:
        data["campus_cam"] = campus_live_cam()
    except Exception as error:
        print("YouTube camera error:", error)

    with open(
        "data.json",
        "w",
        encoding="utf-8"
    ) as file:

        json.dump(data, file, indent=2)

    print(json.dumps(data, indent=2))


if __name__ == "__main__":
    main()
