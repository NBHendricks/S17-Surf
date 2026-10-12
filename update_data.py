import json
import urllib.request
import urllib.parse
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo


# =========================================================
# S17 SURF — CAMPUS POINT
# =========================================================

PACIFIC = ZoneInfo("America/Los_Angeles")

# Approximate ocean location just offshore of Campus Point
CAMPUS_LAT = 34.39
CAMPUS_LON = -119.85

# Campus Point live YouTube camera
CAMERA_ID = "sVENjHlL4Pk"

# NASA/JPL MUR satellite sea-surface-temperature dataset
SATELLITE_URL = (
    "https://coastwatch.pfeg.noaa.gov/erddap/"
    "griddap/jplMURSST41.json"
)


# =========================================================
# DOWNLOAD HELPERS
# =========================================================

def download_text(url):

    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "S17-Surf/4.0"
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

    return json.loads(
        download_text(url)
    )


# =========================================================
# NUMBER HELPERS
# =========================================================

def number(value):

    if value is None:
        return None

    if str(value).upper() in {
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

    except (TypeError, ValueError):
        return None


def meters_to_feet(meters):

    if meters is None:
        return None

    return round(
        meters * 3.28084,
        1
    )


def celsius_to_fahrenheit(celsius):

    if celsius is None:
        return None

    return round(
        celsius * 9 / 5 + 32,
        1
    )


# =========================================================
# NOAA / NDBC BUOY DATA
# =========================================================

def buoy_rows(station):

    url = (
        "https://www.ndbc.noaa.gov/"
        f"data/realtime2/{station}.txt"
    )

    lines = download_text(url).splitlines()

    if len(lines) < 3:

        raise RuntimeError(
            f"No data available from buoy {station}"
        )

    headers = (
        lines[0]
        .lstrip("#")
        .split()
    )

    rows = []

    for line in lines[2:]:

        values = line.split()

        if len(values) < len(headers):
            continue

        row = dict(
            zip(headers, values)
        )

        try:

            observed = datetime(
                int(row["YY"]),
                int(row["MM"]),
                int(row["DD"]),
                int(row["hh"]),
                int(row["mm"]),
                tzinfo=timezone.utc
            )

        except (
            KeyError,
            ValueError
        ):

            continue

        row["_observed"] = observed

        rows.append(row)

    rows.sort(
        key=lambda row: row["_observed"],
        reverse=True
    )

    return rows


def latest_value(
    rows,
    field,
    max_age_hours=6
):

    cutoff = (
        datetime.now(timezone.utc)
        - timedelta(
            hours=max_age_hours
        )
    )

    for row in rows:

        if row["_observed"] < cutoff:
            continue

        value = number(
            row.get(field)
        )

        if value is not None:
            return value

    return None


# =========================================================
# WAVE BUOY DATA
# =========================================================

def wave_buoy(
    station,
    name
):

    rows = buoy_rows(station)

    wave_m = latest_value(
        rows,
        "WVHT"
    )

    period = latest_value(
        rows,
        "DPD"
    )

    direction = latest_value(
        rows,
        "MWD"
    )

    return {

        "station":
            station,

        "name":
            name,

        "wave_height_ft":
            meters_to_feet(
                wave_m
            ),

        "period_sec":
            period,

        "direction_deg":
            direction
    }


# =========================================================
# NASA MUR SATELLITE WATER TEMPERATURE
# =========================================================

def satellite_water_temperature():

    query = (
        "analysed_sst"
        "[(last)]"
        f"[({CAMPUS_LAT})]"
        f"[({CAMPUS_LON})]"
    )

    encoded_query = urllib.parse.quote(
        query,
        safe="[]():-."
    )

    url = (
        SATELLITE_URL
        + "?"
        + encoded_query
    )

    print(
        "Requesting NASA MUR satellite SST..."
    )

    result = download_json(url)

    table = result.get(
        "table",
        {}
    )

    columns = table.get(
        "columnNames",
        []
    )

    rows = table.get(
        "rows",
        []
    )

    if not rows:

        raise RuntimeError(
            "NASA MUR returned no temperature data"
        )

    for row in rows:

        observation = dict(
            zip(
                columns,
                row
            )
        )

        temp_c = number(
            observation.get(
                "analysed_sst"
            )
        )

        if temp_c is None:
            continue

        # Reject impossible SST values
        if not -2 <= temp_c <= 40:
            continue

        observation_time = (
            observation.get("time")
        )

        temp_f = (
            celsius_to_fahrenheit(
                temp_c
            )
        )

        print(
            "NASA MUR SATELLITE SST SUCCESS:",
            temp_f,
            "F"
        )

        return {

            "station":
                "NASA MUR",

            "temp_f":
                temp_f,

            "source":
                (
                    "NASA MUR satellite SST "
                    "near Campus Point"
                ),

            "observed":
                (
                    observation_time
                    if observation_time
                    else "latest available"
                )
        }

    raise RuntimeError(
        "NASA MUR returned no valid SST value"
    )


# =========================================================
# WATER TEMPERATURE
# =========================================================

def water_temperature():

    """
    Water temperature displayed on the S17 card
    comes ONLY from NASA/JPL MUR satellite SST.

    A buoy temperature is deliberately NOT used
    as a fallback.
    """

    try:

        satellite = (
            satellite_water_temperature()
        )

        if (
            satellite
            and satellite.get(
                "temp_f"
            ) is not None
        ):

            return satellite

    except Exception as error:

        print(
            "NASA MUR SATELLITE ERROR:",
            error
        )

    # Do NOT substitute Harvest or another buoy.
    return {

        "station":
            "NASA MUR",

        "temp_f":
            None,

        "source":
            (
                "NASA MUR satellite SST "
                "temporarily unavailable"
            ),

        "observed":
            None
    }


# =========================================================
# EXPERIMENTAL CAMPUS POINT SURF ESTIMATE
# =========================================================

def estimate_campus_surf(
    harvest,
    channel
):

    """
    Experimental Campus Point breaking-wave estimate.

    Harvest 46218 is the primary swell source.

    East Santa Barbara 46053 is used as an
    additional reference only when it actually
    has valid wave-height data.

    This is not a measured Campus Point wave height.
    """

    # Harvest is required.
    # East Santa Barbara is NOT required.

    if not harvest:
        return None

    harvest_height = harvest.get(
        "wave_height_ft"
    )

    period = harvest.get(
        "period_sec"
    )

    direction = harvest.get(
        "direction_deg"
    )

    if (
        harvest_height is None
        or period is None
        or direction is None
    ):

        return None


    # =====================================================
    # CAMPUS POINT DIRECTIONAL EXPOSURE
    # =====================================================
    #
    # Campus Point is protected from steep NW swell.
    # More westerly swell has better exposure.
    #
    # These factors are experimental and can later
    # be calibrated against the Campus Point camera.
    # =====================================================

    if 255 <= direction <= 280:

        exposure = 0.42

    elif 245 <= direction < 255:

        exposure = 0.34

    elif 280 < direction <= 290:

        exposure = 0.32

    elif 235 <= direction < 245:

        exposure = 0.25

    elif 290 < direction <= 300:

        exposure = 0.22

    elif 225 <= direction < 235:

        exposure = 0.18

    elif 300 < direction <= 310:

        exposure = 0.15

    elif 310 < direction <= 320:

        exposure = 0.11

    elif 320 < direction <= 330:

        exposure = 0.08

    elif 330 < direction <= 340:

        exposure = 0.06

    else:

        exposure = 0.05


    # =====================================================
    # PERIOD / ENERGY ADJUSTMENT
    # =====================================================

    if period >= 18:

        period_factor = 1.35

    elif period >= 16:

        period_factor = 1.25

    elif period >= 14:

        period_factor = 1.15

    elif period >= 12:

        period_factor = 1.05

    elif period >= 10:

        period_factor = 0.95

    elif period >= 8:

        period_factor = 0.80

    else:

        period_factor = 0.65


    # =====================================================
    # HARVEST-BASED ESTIMATE
    # =====================================================

    estimated = (
        harvest_height
        * exposure
        * period_factor
    )


    # =====================================================
    # OPTIONAL EAST SANTA BARBARA ADJUSTMENT
    # =====================================================

    channel_height = None

    if channel:

        channel_height = channel.get(
            "wave_height_ft"
        )


    # If East Santa Barbara has real wave data,
    # use it as additional information.
    #
    # If it is null, Harvest continues by itself.

    if channel_height is not None:

        estimated = (
            estimated * 0.65
            + channel_height * 0.35
        )


    # =====================================================
    # CONVERT ESTIMATE INTO DISPLAY RANGE
    # =====================================================

    low = round(
        estimated * 0.75 * 2
    ) / 2

    high = round(
        estimated * 1.35 * 2
    ) / 2

    low = max(
        0.5,
        low
    )

    high = max(
        low + 0.5,
        high
    )


    return {

        "low_ft":
            low,

        "high_ft":
            high,

        "method":
            (
                "Harvest swell adjusted for "
                "Campus Point exposure"
            ),

        "inputs": {

            "harvest_height_ft":
                harvest_height,

            "period_sec":
                period,

            "direction_deg":
                direction,

            "channel_height_ft":
                channel_height
        },

        "disclaimer":
            (
                "Experimental estimate only. "
                "Not a measured or validated "
                "Campus Point breaking-wave height."
            )
    }


# =========================================================
# NOAA SANTA BARBARA TIDES
# =========================================================

def tide_data(today):

    date_string = (
        today.strftime(
            "%Y%m%d"
        )
    )

    params = {

        "product":
            "predictions",

        "application":
            "S17-Surf",

        "begin_date":
            date_string,

        "end_date":
            date_string,

        "datum":
            "MLLW",

        "station":
            "9411340",

        "time_zone":
            "lst_ldt",

        "units":
            "english",

        "interval":
            "hilo",

        "format":
            "json"
    }

    url = (
        "https://api.tidesandcurrents.noaa.gov/"
        "api/prod/datagetter?"
        + urllib.parse.urlencode(
            params
        )
    )

    result = download_json(url)

    tides = []

    for item in result.get(
        "predictions",
        []
    ):

        timestamp = datetime.strptime(
            item["t"],
            "%Y-%m-%d %H:%M"
        )

        tides.append({

            "type":
                (
                    "HIGH"
                    if item["type"] == "H"
                    else "LOW"
                ),

            "time":
                timestamp.strftime(
                    "%-I:%M %p"
                ),

            "height_ft":
                round(
                    float(
                        item["v"]
                    ),
                    1
                )
        })

    return tides


# =========================================================
# MAIN
# =========================================================

def main():

    now = datetime.now(
        PACIFIC
    )

    data = {

        "location":
            "Campus Point, California",

        "date_display":
            now.strftime(
                "%A, %B %-d, %Y"
            ),

        "updated_display":
            now.strftime(
                "%-I:%M %p %Z"
            ),

        "harvest":
            None,

        "channel":
            None,

        "surf_estimate":
            None,

        "water_temp":
            None,

        "tides":
            [],

        "campus_cam": {

            "video_id":
                CAMERA_ID,

            "title":
                "Campus Point Surf Cam"
        }
    }


    # =====================================================
    # HARVEST BUOY 46218
    # =====================================================

    try:

        data["harvest"] = wave_buoy(
            "46218",
            "Harvest"
        )

    except Exception as error:

        print(
            "Harvest buoy error:",
            error
        )


    # =====================================================
    # EAST SANTA BARBARA BUOY 46053
    # =====================================================

    try:

        data["channel"] = wave_buoy(
            "46053",
            "East Santa Barbara"
        )

    except Exception as error:

        print(
            "East Santa Barbara buoy error:",
            error
        )


    # =====================================================
    # NASA SATELLITE WATER TEMPERATURE
    # =====================================================

    data["water_temp"] = (
        water_temperature()
    )


    # =====================================================
    # CAMPUS POINT SURF ESTIMATE
    # =====================================================

    data["surf_estimate"] = (
        estimate_campus_surf(
            data["harvest"],
            data["channel"]
        )
    )


    # =====================================================
    # TIDES
    # =====================================================

    try:

        data["tides"] = (
            tide_data(now)
        )

    except Exception as error:

        print(
            "Tide error:",
            error
        )


    # =====================================================
    # SAVE DATA.JSON
    # =====================================================

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
