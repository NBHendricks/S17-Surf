import json
import urllib.request
import urllib.parse
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo


# =========================================================
# S17 SURF — CAMPUS POINT
# =========================================================

PACIFIC = ZoneInfo("America/Los_Angeles")

# Approximate ocean point immediately offshore of Campus Point.
CAMPUS_LAT = 34.39
CAMPUS_LON = -119.85

# Confirmed Campus Point YouTube stream.
CAMERA_ID = "sVENjHlL4Pk"

# NASA/JPL MUR sea-surface-temperature dataset via NOAA CoastWatch.
SATELLITE_URL = (
    "https://coastwatch.pfeg.noaa.gov/erddap/"
    "griddap/jplMURSST41.json"
)


# =========================================================
# BASIC DOWNLOAD FUNCTIONS
# =========================================================

def download_text(url):

    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "S17-Surf/3.0"
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
# WAVE BUOY
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

    water_c = latest_value(
        rows,
        "WTMP",
        max_age_hours=24
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
            direction,

        "water_temp_f":
            celsius_to_fahrenheit(
                water_c
            )
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
            "No NASA MUR temperature returned"
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

        # Reject physically unrealistic values.
        if not -2 <= temp_c <= 40:
            continue

        observation_time = (
            observation.get("time")
        )

        # Some ERDDAP responses may not include
        # time in the returned columns.
        observed_display = (
            observation_time
            if observation_time
            else "latest available"
        )

        if observation_time:

            try:

                observed = (
                    datetime.fromisoformat(
                        observation_time.replace(
                            "Z",
                            "+00:00"
                        )
                    )
                )

                age_hours = (
                    datetime.now(timezone.utc)
                    - observed
                ).total_seconds() / 3600

                # MUR is a daily product, so allow
                # several days for processing delays.
                if age_hours > 120:

                    raise RuntimeError(
                        "NASA MUR temperature is too old"
                    )

            except ValueError:

                pass

        return {

            "station":
                "NASA MUR",

            "temp_f":
                celsius_to_fahrenheit(
                    temp_c
                ),

            "source":
                "NASA MUR satellite SST near Campus Point",

            "observed":
                observed_display
        }

    raise RuntimeError(
        "No valid NASA MUR temperature"
    )


# =========================================================
# BACKUP BUOY WATER TEMPERATURE
# =========================================================

def backup_water_temperature(
    channel,
    harvest
):

    # First choice:
    # East Santa Barbara buoy.

    for buoy in [
        channel,
        harvest
    ]:

        if not buoy:
            continue

        temp_f = buoy.get(
            "water_temp_f"
        )

        if temp_f is None:
            continue

        return {

            "station":
                buoy["station"],

            "temp_f":
                temp_f,

            "source":
                (
                    "NOAA buoy "
                    + buoy["station"]
                    + " — "
                    + buoy["name"]
                )
        }

    return None


# =========================================================
# CHOOSE WATER TEMPERATURE
# =========================================================

def water_temperature(
    channel,
    harvest
):

    # PRIMARY:
    # NASA satellite SST.

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

            print(
                "Using NASA MUR water temperature:",
                satellite["temp_f"],
                "F"
            )

            return satellite

    except Exception as error:

        print(
            "NASA MUR temperature error:",
            error
        )

    # BACKUP:
    # Actual buoy thermometer.

    backup = backup_water_temperature(
        channel,
        harvest
    )

    if backup:

        print(
            "Using backup buoy water temperature:",
            backup["temp_f"],
            "F"
        )

        return backup

    return {

        "station":
            None,

        "temp_f":
            None,

        "source":
            "Water temperature unavailable"
    }


# =========================================================
# EXPERIMENTAL CAMPUS POINT SURF ESTIMATE
# =========================================================

def estimate_campus_surf(
    harvest,
    channel
):

    """
    Experimental estimate only.

    This is NOT a measured Campus Point wave height
    and NOT a calibrated numerical surf model.

    The East Santa Barbara buoy provides the
    in-channel wave-energy reference.

    Harvest provides information about incoming
    swell direction and period.
    """

    if not harvest or not channel:
        return None

    channel_height = channel.get(
        "wave_height_ft"
    )

    harvest_period = harvest.get(
        "period_sec"
    )

    harvest_direction = harvest.get(
        "direction_deg"
    )

    if (
        channel_height is None
        or harvest_period is None
        or harvest_direction is None
    ):
        return None


    # -----------------------------------------
    # DIRECTION FACTOR
    # -----------------------------------------

    # More westerly swell generally has better
    # opportunity to enter the Santa Barbara
    # Channel than steep NW swell.

    if 250 <= harvest_direction <= 285:

        direction_factor = 1.00

    elif 235 <= harvest_direction < 250:

        direction_factor = 0.85

    elif 285 < harvest_direction <= 300:

        direction_factor = 0.75

    elif 220 <= harvest_direction < 235:

        direction_factor = 0.65

    elif 300 < harvest_direction <= 315:

        direction_factor = 0.55

    else:

        direction_factor = 0.45


    # -----------------------------------------
    # PERIOD FACTOR
    # -----------------------------------------

    # Longer-period swell carries more energy
    # and refracts differently around coastal
    # features.

    if harvest_period >= 17:

        period_factor = 1.20

    elif harvest_period >= 14:

        period_factor = 1.10

    elif harvest_period >= 11:

        period_factor = 1.00

    elif harvest_period >= 8:

        period_factor = 0.85

    else:

        period_factor = 0.70


    center = (
        channel_height
        * direction_factor
        * period_factor
    )


    # -----------------------------------------
    # CREATE A RANGE
    # -----------------------------------------

    low = round(
        center * 0.65 * 2
    ) / 2

    high = round(
        center * 1.35 * 2
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
            "Harvest + East Santa Barbara",

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
# MAIN UPDATE
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


    # -----------------------------------------
    # HARVEST 46218
    # -----------------------------------------

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


    # -----------------------------------------
    # EAST SANTA BARBARA 46053
    # -----------------------------------------

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


    # -----------------------------------------
    # WATER TEMPERATURE
    # -----------------------------------------

    data["water_temp"] = (
        water_temperature(
            data["channel"],
            data["harvest"]
        )
    )


    # -----------------------------------------
    # CAMPUS POINT SURF ESTIMATE
    # -----------------------------------------

    data["surf_estimate"] = (
        estimate_campus_surf(
            data["harvest"],
            data["channel"]
        )
    )


    # -----------------------------------------
    # TIDES
    # -----------------------------------------

    try:

        data["tides"] = (
            tide_data(now)
        )

    except Exception as error:

        print(
            "Tide error:",
            error
        )


    # -----------------------------------------
    # SAVE DATA.JSON
    # -----------------------------------------

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
