import json
import os
import urllib.request
import urllib.parse

from datetime import datetime
from zoneinfo import ZoneInfo


PACIFIC = ZoneInfo("America/Los_Angeles")


def download_text(url):

    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "S17-Surf/1.0"
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


def parse_ndbc(station):

    url = (
        "https://www.ndbc.noaa.gov/"
        f"data/realtime2/{station}.txt"
    )

    text = download_text(url)

    lines = [
        line.strip()
        for line in text.splitlines()
        if line.strip()
    ]

    if len(lines) < 3:
        raise RuntimeError(
            f"No observations for {station}"
        )

    headers = lines[0].lstrip("#").split()

    for line in lines[2:]:

        values = line.split()

        if len(values) < len(headers):
            continue

        return dict(
            zip(headers, values)
        )

    raise RuntimeError(
        f"No valid row for {station}"
    )


def number(value):

    if value is None:
        return None

    if value in {
        "MM",
        "999",
        "999.0",
        "99.0",
        "9999"
    }:
        return None

    try:
        return float(value)

    except ValueError:
        return None


def harvest_data():

    row = parse_ndbc("46218")

    wave_m = number(
        row.get("WVHT")
    )

    period = number(
        row.get("DPD")
    )

    direction = number(
        row.get("MWD")
    )

    return {
        "wave_height_ft":
            round(
                wave_m * 3.28084,
                1
            )
            if wave_m is not None
            else None,

        "period_sec":
            period,

        "direction_deg":
            direction
    }


def campus_water_temp():

    row = parse_ndbc("46053")

    water_c = number(
        row.get("WTMP")
    )

    return {
        "station": "46053",

        "temp_f":
            round(
                water_c * 9 / 5 + 32,
                1
            )
            if water_c is not None
            else None
    }


def tide_data(today):

    date_string = today.strftime(
        "%Y%m%d"
    )

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

    result = json.loads(
        download_text(url)
    )

    predictions = result.get(
        "predictions",
        []
    )

    tides = []

    for tide in predictions:

        timestamp = datetime.strptime(
            tide["t"],
            "%Y-%m-%d %H:%M"
        )

        tides.append({
            "type":
                "HIGH"
                if tide["type"] == "H"
                else "LOW",

            "time":
                timestamp.strftime(
                    "%-I:%M %p"
                ),

            "height_ft":
                round(
                    float(tide["v"]),
                    1
                )
        })

    return tides


def campus_live_cam():

    api_key = os.environ.get(
        "YOUTUBE_API_KEY"
    )

    if not api_key:
        print("No YouTube API key available")
        return None

    params = {
        "part": "snippet",
        "q": "Campus Point Surf Cam GRIT",
        "type": "video",
        "eventType": "live",
        "maxResults": "5",
        "videoEmbeddable": "true",
        "key": api_key
    }

    url = (
        "https://www.googleapis.com/"
        "youtube/v3/search?"
        + urllib.parse.urlencode(params)
    )

    data = json.loads(
        download_text(url)
    )

    items = data.get(
        "items",
        []
    )

    for item in items:

        snippet = item.get(
            "snippet",
            {}
        )

        title = snippet.get(
            "title",
            ""
        ).lower()

        channel = snippet.get(
            "channelTitle",
            ""
        ).lower()

        video_id = (
            item
            .get("id", {})
            .get("videoId")
        )

        if (
            video_id
            and
            "campus point" in title
            and
            "grit" in channel
        ):

            return {
                "video_id": video_id,
                "title": snippet.get("title"),
                "channel": snippet.get(
                    "channelTitle"
                )
            }

    for item in items:

        video_id = (
            item
            .get("id", {})
            .get("videoId")
        )

        if video_id:

            snippet = item.get(
                "snippet",
                {}
            )

            return {
                "video_id": video_id,
                "title": snippet.get("title"),
                "channel": snippet.get(
                    "channelTitle"
                )
            }

    return None


def main():

    now = datetime.now(
        PACIFIC
    )

    data = {
        "date_display":
            now.strftime(
                "%A, %B %-d, %Y"
            ),

        "updated_display":
            now.strftime(
                "%-I:%M %p %Z"
            ),

        "harvest": None,
        "water_temp": None,
        "tides": [],
        "campus_cam": None
    }

    try:
        data["harvest"] = (
            harvest_data()
        )

    except Exception as error:
        print(
            "Harvest error:",
            error
        )

    try:
        data["water_temp"] = (
            campus_water_temp()
        )

    except Exception as error:
        print(
            "Water temp error:",
            error
        )

    try:
        data["tides"] = (
            tide_data(now)
        )

    except Exception as error:
        print(
            "Tide error:",
            error
        )

    try:
        data["campus_cam"] = (
            campus_live_cam()
        )

    except Exception as error:
        print(
            "Campus cam error:",
            error
        )

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

    print(
        json.dumps(
            data,
            indent=2
        )
    )


if __name__ == "__main__":
    main()
