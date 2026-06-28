import os
import json
import requests
from datetime import datetime
from dotenv import load_dotenv
from time import time
from mcp.server.fastmcp import FastMCP


BASE_DIR = os.path.dirname(os.path.abspath(__file__))
TOKEN_FILE = os.path.join(BASE_DIR, 'strava_token.json')
CONFIG_FILE = os.path.join(BASE_DIR, 'user_config.json')

SPORT_TYPES = {
    'run':    ['Run', 'TrailRun', 'VirtualRun'],
    'cycle':  ['Ride', 'MountainBikeRide', 'GravelRide', 'VirtualRide', 'EBikeRide'],
    'swim':   ['Swim', 'OpenWaterSwim'],
    'hike':   ['Hike', 'Walk', 'NordicSki', 'BackcountrySki'],
}


def load_user_config() -> dict:
    if not os.path.exists(CONFIG_FILE):
        return {}
    with open(CONFIG_FILE) as f:
        return json.load(f)


def save_user_config(config: dict) -> None:
    with open(CONFIG_FILE, 'w') as f:
        json.dump(config, f, indent=2)


def check_expired_token(expiry):
    return time() > expiry


def save_tokens(tokens) -> None:
    data = {
        'access_token': tokens['access_token'],
        'refresh_token': tokens['refresh_token'],
        'expires_at': tokens['expires_at']
    }
    with open(TOKEN_FILE, 'w') as f:
        json.dump(data, f)


def refresh_strava_tokens(tokens):
    response = requests.post('https://www.strava.com/oauth/token', data={
        'client_id': os.environ.get('STRAVA_CLIENT_ID'),
        'client_secret': os.environ.get('STRAVA_CLIENT_SECRET'),
        'refresh_token': tokens['refresh_token'],
        'grant_type': 'refresh_token'
    })
    save_tokens(response.json())


def validate_strava_token():
    with open(TOKEN_FILE) as f:
        tokens = json.load(f)
    if check_expired_token(tokens['expires_at']):
        refresh_strava_tokens(tokens)
        with open(TOKEN_FILE) as f:
            tokens = json.load(f)
    return tokens['access_token']


def format_seconds(seconds: int) -> str:
    seconds = int(seconds)
    h = seconds // 3600
    m = (seconds % 3600) // 60
    s = seconds % 60
    return f"{h}:{m:02d}:{s:02d}"


def _sport_category(activity_type: str) -> str:
    for category, types in SPORT_TYPES.items():
        if activity_type in types:
            return category
    return 'other'


def _format_pace(speed_ms: float, sport: str = 'run') -> str:
    if not speed_ms:
        return 'N/A'
    if sport == 'swim':
        pace_secs = int(100 / speed_ms)
        return f"{pace_secs // 60}:{pace_secs % 60:02d} /100m"
    if sport == 'cycle':
        return f"{speed_ms * 3.6:.1f} km/h"
    pace_secs = int(1000 / speed_ms)
    return f"{pace_secs // 60}:{pace_secs % 60:02d} /km"


def _format_date(date_str: str) -> str:
    return datetime.strptime(date_str, "%Y-%m-%dT%H:%M:%SZ").strftime("%Y-%m-%d %H:%M")


def _reverse_geocode(latlng: list) -> str:
    if not latlng or len(latlng) < 2:
        return None
    try:
        response = requests.get(
            'https://nominatim.openstreetmap.org/reverse',
            params={'lat': latlng[0], 'lon': latlng[1], 'format': 'json', 'zoom': 10},
            headers={'User-Agent': 'strava-mcp-server/1.0'},
            timeout=5
        )
        data = response.json()
        addr = data.get('address', {})
        # prefer suburb/village > town/city > county, skip country
        parts = [addr.get(k) for k in ('suburb', 'village', 'town', 'city', 'county') if addr.get(k)]
        return ', '.join(parts[:2]) if parts else data.get('display_name', '').split(',')[0]
    except Exception:
        return None


def _format_activity(a: dict) -> str:
    sport = _sport_category(a.get('type', ''))
    location = _reverse_geocode(a.get('start_latlng'))
    location_str = f" — {location}" if location else ""
    lines = [
        f"  [{a['id']}] {a['name']} ({a.get('type', 'Unknown')}) — {_format_date(a['start_date_local'])}{location_str}",
        f"  Distance: {a['distance'] / 1000:.2f} km | Time: {format_seconds(a['moving_time'])} | {_format_pace(a.get('average_speed', 0), sport)}",
        f"  Elevation: {a['total_elevation_gain']} m",
    ]
    if a.get('average_heartrate'):
        lines.append(f"  HR: avg {a['average_heartrate']:.0f} bpm / max {a.get('max_heartrate', 'N/A'):.0f} bpm")
    if a.get('average_cadence'):
        unit = 'rpm' if sport == 'cycle' else 'spm'
        lines.append(f"  Cadence: {a['average_cadence']:.0f} {unit}")
    if a.get('average_watts'):
        lines.append(f"  Power: avg {a['average_watts']:.0f}w")
    if a.get('suffer_score'):
        lines.append(f"  Suffer score: {a['suffer_score']}")
    return '\n'.join(lines)


def _fetch_streams(activity_id: int, keys: list) -> dict:
    headers = {'Authorization': f'Bearer {ACCESS_TOKEN}'}
    response = requests.get(
        f'https://www.strava.com/api/v3/activities/{activity_id}/streams',
        headers=headers,
        params={'keys': ','.join(keys), 'key_by_type': 'true'}
    )
    if response.status_code == 404:
        return {}
    return response.json()


def _hr_zone_analysis(hr_data: list, max_hr: int) -> list:
    total = len(hr_data)
    zone_bounds = [(0, 0.60), (0.60, 0.70), (0.70, 0.80), (0.80, 0.90), (0.90, 1.01)]
    zone_counts = [sum(1 for h in hr_data if max_hr * lo <= h < max_hr * hi) for lo, hi in zone_bounds]
    lines = []
    for i, count in enumerate(zone_counts, 1):
        bar = '█' * (count * 20 // total)
        lines.append(f"  Z{i} ({int(max_hr * zone_bounds[i-1][0])}-{int(max_hr * zone_bounds[i-1][1])} bpm): {count * 100 // total:3d}%  {bar}")
    return lines


def _hr_drift_analysis(hr_data: list) -> list:
    mid = len(hr_data) // 2
    first = sum(hr_data[:mid]) / mid
    second = sum(hr_data[mid:]) / (len(hr_data) - mid)
    drift = (second - first) / first * 100
    return [
        f"  First half avg HR:  {first:.0f} bpm",
        f"  Second half avg HR: {second:.0f} bpm",
        f"  Drift: {drift:+.1f}% ({'good aerobic fitness' if abs(drift) < 5 else 'some cardiac drift — consider easier effort'})",
    ]


def _power_zone_analysis(watts_data: list, ftp: int) -> list:
    zone_bounds = [(0, 0.55), (0.55, 0.75), (0.75, 0.90), (0.90, 1.05), (1.05, 1.20), (1.20, 2.0)]
    zone_names = ['Z1 Active Recovery', 'Z2 Endurance', 'Z3 Tempo', 'Z4 Threshold', 'Z5 VO2max', 'Z6 Anaerobic']
    total = len(watts_data)
    lines = []
    for name, (lo, hi) in zip(zone_names, zone_bounds):
        count = sum(1 for w in watts_data if ftp * lo <= w < ftp * hi)
        bar = '█' * (count * 20 // total)
        lines.append(f"  {name} ({int(ftp * lo)}-{int(ftp * hi)}w): {count * 100 // total:3d}%  {bar}")
    return lines


load_dotenv()
ACCESS_TOKEN = validate_strava_token()

mcp = FastMCP(
    "strava",
    instructions=(
        "You have access to the user's real Strava training data via these tools. "
        "Always use these tools when the user asks anything about their runs, rides, swims, hikes, workouts, training, pace, distance, fitness, or athletic performance — "
        "never answer from memory or make up data. "
        "Today's date is " + datetime.now().strftime("%Y-%m-%d") + "."
    )
)

METRIC_CONFIG = {
    'pace':      {'key': lambda a: a.get('average_speed', 0),       'reverse': False, 'filter': lambda a: a.get('average_speed', 0) > 0},
    'distance':  {'key': lambda a: a.get('distance', 0),            'reverse': True,  'filter': lambda a: a.get('distance', 0) > 0},
    'time':      {'key': lambda a: a.get('moving_time', 0),         'reverse': True,  'filter': lambda a: True},
    'elevation': {'key': lambda a: a.get('total_elevation_gain', 0),'reverse': True,  'filter': lambda a: True},
    'power':     {'key': lambda a: a.get('average_watts', 0),       'reverse': True,  'filter': lambda a: a.get('average_watts', 0) > 0},
}


@mcp.tool()
def ping() -> str:
    """Use this to verify the server is running."""
    return f"pong — token: {ACCESS_TOKEN[:6]}..."


@mcp.tool()
def get_athlete_stats() -> str:
    """Returns the athlete's stats across running, cycling, and swimming: recent (4-week), YTD, and all-time totals. Always use this when the user asks about their overall training volume, yearly mileage, or fitness summary."""
    headers = {'Authorization': f'Bearer {ACCESS_TOKEN}'}
    athlete = requests.get('https://www.strava.com/api/v3/athlete', headers=headers).json()
    stats = requests.get(f'https://www.strava.com/api/v3/athletes/{athlete["id"]}/stats', headers=headers).json()

    def _fmt(totals: dict, label: str) -> str:
        return (
            f"{label}:\n"
            f"  Distance: {totals['distance'] / 1000:.2f} km | "
            f"Time: {format_seconds(totals['moving_time'])} | "
            f"Elevation: {totals['elevation_gain']} m | "
            f"Count: {totals['count']}"
        )

    sections = [f"Stats as of {datetime.now().strftime('%-d %B %Y')}:\n"]
    for sport, keys in [('Running', 'run'), ('Cycling', 'ride'), ('Swimming', 'swim')]:
        sections.append(f"── {sport} ──")
        sections.append(_fmt(stats[f'recent_{keys}_totals'], 'Recent (4 weeks)'))
        sections.append(_fmt(stats[f'ytd_{keys}_totals'], 'YTD'))
        sections.append(_fmt(stats[f'all_{keys}_totals'], 'All time'))
        sections.append('')
    return '\n'.join(sections)


@mcp.tool()
def get_recent_activities(count: int = 10, after: str = None, before: str = None) -> str:
    """Returns the athlete's activities across all sports. Always use this when the user asks about specific workouts or training on a particular date. Returns activity IDs for use with get_activity_detail.
    count: number of activities to return (default 10).
    after: only return activities after this date (YYYY-MM-DD).
    before: only return activities before this date (YYYY-MM-DD).
    """
    headers = {'Authorization': f'Bearer {ACCESS_TOKEN}'}
    params = {'per_page': count}
    if after:
        params['after'] = int(datetime.strptime(after, "%Y-%m-%d").timestamp())
    if before:
        params['before'] = int(datetime.strptime(before, "%Y-%m-%d").timestamp())
    activities = requests.get('https://www.strava.com/api/v3/athlete/activities', headers=headers, params=params).json()
    if not activities:
        return "No activities found."
    return f"{len(activities)} activities found:\n\n" + '\n\n'.join(_format_activity(a) for a in activities)


@mcp.tool()
def get_activity_detail(activity_id: int) -> str:
    """Returns full detail for a single activity including splits, heart rate, cadence, power (cycling), and perceived exertion. Always use this when the user wants to analyse a specific workout in depth. Get the activity_id from get_recent_activities first."""
    headers = {'Authorization': f'Bearer {ACCESS_TOKEN}'}
    response = requests.get(f'https://www.strava.com/api/v3/activities/{activity_id}', headers=headers)
    if response.status_code == 404:
        return f"Activity {activity_id} not found."
    a = response.json()
    sport = _sport_category(a.get('type', ''))

    location = _reverse_geocode(a.get('start_latlng'))
    lines = [
        f"{a['name']} ({a.get('type', 'Unknown')}) — {_format_date(a['start_date_local'])}",
        f"Location: {location}" if location else "Location: unknown",
        f"Distance: {a['distance'] / 1000:.2f} km | Time: {format_seconds(a['moving_time'])} | {_format_pace(a.get('average_speed', 0), sport)}",
        f"Elevation: {a['total_elevation_gain']} m",
    ]
    if a.get('description'):
        lines.append(f"Description: {a['description']}")
    if a.get('average_heartrate'):
        lines.append(f"HR: avg {a['average_heartrate']:.0f} bpm / max {a.get('max_heartrate', 'N/A'):.0f} bpm")
    if a.get('average_cadence'):
        unit = 'rpm' if sport == 'cycle' else 'spm'
        lines.append(f"Cadence: {a['average_cadence']:.0f} {unit}")
    if sport == 'cycle' and a.get('average_watts'):
        lines.append(f"Power: avg {a['average_watts']:.0f}w / max {a.get('max_watts', 'N/A')}w")
        if a.get('weighted_average_watts'):
            lines.append(f"Normalised power: {a['weighted_average_watts']}w")
    if a.get('suffer_score'):
        lines.append(f"Suffer score: {a['suffer_score']}")
    if a.get('perceived_exertion'):
        lines.append(f"Perceived exertion: {a['perceived_exertion']}")
    if a.get('calories'):
        lines.append(f"Calories: {a['calories']}")
    if a.get('device_name'):
        lines.append(f"Device: {a['device_name']}")

    if sport == 'swim' and a.get('laps'):
        lines.append("\nLaps:")
        for lap in a['laps']:
            lines.append(f"  Lap {lap['lap_index']}: {lap['distance']:.0f}m | {format_seconds(lap['moving_time'])} | {_format_pace(lap.get('average_speed', 0), 'swim')}")
    elif a.get('splits_metric'):
        lines.append(f"\n{'km' if sport != 'swim' else '100m'} splits:")
        for split in a['splits_metric']:
            pace = _format_pace(split.get('average_speed', 0), sport)
            hr = f" | HR {split['average_heartrate']:.0f}" if split.get('average_heartrate') else ''
            elev = f" | elev {split['elevation_difference']:+.0f}m" if split.get('elevation_difference') else ''
            lines.append(f"  {split['split']}: {pace}{hr}{elev}")

    return '\n'.join(lines)


@mcp.tool()
def get_best_activities(metric: str = "pace", top_n: int = 5, activity_type: str = "Run") -> str:
    """Returns the athlete's best activities ranked by a metric. Always use this when the user asks about their fastest, longest, hardest, or highest-elevation workouts.
    metric: one of 'pace' (fastest), 'distance' (longest), 'time' (longest duration), 'elevation' (most climb), 'power' (highest avg power, cycling only).
    top_n: how many results to return (default 5).
    activity_type: e.g. 'Run', 'TrailRun', 'Ride', 'Swim', 'Hike' (default 'Run').
    """
    if metric not in METRIC_CONFIG:
        return f"Unknown metric '{metric}'. Choose from: {', '.join(METRIC_CONFIG.keys())}."

    headers = {'Authorization': f'Bearer {ACCESS_TOKEN}'}
    all_activities = requests.get(
        'https://www.strava.com/api/v3/athlete/activities',
        headers=headers,
        params={'per_page': 200}
    ).json()

    filtered = [a for a in all_activities if a.get('type') == activity_type or a.get('sport_type') == activity_type]
    config = METRIC_CONFIG[metric]
    filtered = [a for a in filtered if config['filter'](a)]
    ranked = sorted(filtered, key=config['key'], reverse=config['reverse'])[:top_n]

    if not ranked:
        return f"No {activity_type} activities found."

    sport = _sport_category(activity_type)
    label = {'pace': 'fastest', 'distance': 'longest', 'time': 'longest by time', 'elevation': 'most elevation', 'power': 'highest power'}[metric]
    lines = [f"Top {len(ranked)} {label} {activity_type.lower()}s:\n"]
    for i, a in enumerate(ranked, 1):
        if metric == 'pace':
            stat = _format_pace(a.get('average_speed', 0), sport)
        elif metric == 'distance':
            stat = f"Distance: {a['distance'] / 1000:.2f} km"
        elif metric == 'time':
            stat = f"Time: {format_seconds(a['moving_time'])}"
        elif metric == 'elevation':
            stat = f"Elevation: {a['total_elevation_gain']} m"
        else:
            stat = f"Power: {a.get('average_watts', 0):.0f}w"
        lines.append(f"{i}. [{a['id']}] {a['name']} — {_format_date(a['start_date_local'])} | {stat}")

    return '\n'.join(lines)


@mcp.tool()
def set_max_hr(max_hr: int) -> str:
    """Saves the athlete's maximum heart rate for use in HR zone calculations. Always call this when the user tells you their max HR. Accurate max HR makes zone analysis significantly more meaningful."""
    if max_hr < 100 or max_hr > 250:
        return f"Max HR of {max_hr} bpm looks incorrect — expected a value between 100 and 250."
    config = load_user_config()
    config['max_hr'] = max_hr
    save_user_config(config)
    return f"Max HR set to {max_hr} bpm. Future HR zone analysis will use this value."


@mcp.tool()
def set_ftp(ftp: int) -> str:
    """Saves the athlete's functional threshold power (FTP) for use in cycling power zone analysis. Always call this when the user tells you their FTP."""
    if ftp < 50 or ftp > 600:
        return f"FTP of {ftp}w looks incorrect — expected a value between 50 and 600."
    config = load_user_config()
    config['ftp'] = ftp
    save_user_config(config)
    return f"FTP set to {ftp}w. Future cycling power zone analysis will use this value."


@mcp.tool()
def get_activity_streams(activity_id: int, stream_types: str = "heartrate,velocity_smooth,cadence,altitude") -> str:
    """Returns raw time-series data for an activity — one data point per second for HR, pace, cadence, and altitude.
    Use this when the user wants to see exactly how a metric changed over the course of a workout, e.g. 'show me my HR trace' or 'how did my pace change throughout the run'.
    For summary insights (zone distribution, HR drift, effort quality) use get_activity_analysis instead.
    stream_types: comma-separated list — options: heartrate, velocity_smooth, cadence, altitude, watts, distance.
    """
    keys = [k.strip() for k in stream_types.split(',')]
    streams = _fetch_streams(activity_id, keys)
    if not streams:
        return f"No stream data found for activity {activity_id}."

    lines = [f"Stream data for activity {activity_id} ({len(next(iter(streams.values()))['data'])} seconds):\n"]
    for stream_type, stream in streams.items():
        data = stream['data']
        if stream_type == 'heartrate':
            lines.append(f"Heart rate (bpm): min {min(data)}, max {max(data)}, avg {sum(data)/len(data):.0f}")
            lines.append(f"  Trace (every 30s): {data[::30]}")
        elif stream_type == 'velocity_smooth':
            paces = [_format_pace(v) for v in data[::30] if v > 0]
            lines.append(f"Pace (every 30s): {paces}")
        elif stream_type == 'watts':
            lines.append(f"Power (w): min {min(data)}, max {max(data)}, avg {sum(data)/len(data):.0f}")
            lines.append(f"  Trace (every 30s): {data[::30]}")
        elif stream_type == 'cadence':
            lines.append(f"Cadence: min {min(data)}, max {max(data)}, avg {sum(data)/len(data):.0f}")
        elif stream_type == 'altitude':
            lines.append(f"Altitude (m): min {min(data):.0f}, max {max(data):.0f}")
            lines.append(f"  Trace (every 30s): {[round(d, 1) for d in data[::30]]}")

    return '\n'.join(lines)


@mcp.tool()
def get_activity_analysis(activity_id: int) -> str:
    """Returns a structured training analysis tailored to the sport — HR zone distribution, aerobic decoupling, and effort quality for runs/hikes/swims; power zones and normalised power for cycling.
    Use this when the user wants to understand workout quality, e.g. 'how was my aerobic effort?', 'was I in zone 2?', 'did my HR drift?', 'analyse my ride'.
    For raw second-by-second data use get_activity_streams instead.
    """
    headers = {'Authorization': f'Bearer {ACCESS_TOKEN}'}
    activity = requests.get(f'https://www.strava.com/api/v3/activities/{activity_id}', headers=headers).json()
    sport = _sport_category(activity.get('type', ''))

    streams = _fetch_streams(activity_id, ['heartrate', 'velocity_smooth', 'cadence', 'watts'])
    config = load_user_config()

    lines = [f"Training analysis: {activity['name']} ({activity.get('type', 'Unknown')}) — {_format_date(activity['start_date_local'])}\n"]

    # HR analysis — applies to all sports
    if 'heartrate' in streams:
        hr_data = streams['heartrate']['data']
        if 'max_hr' in config:
            max_hr = config['max_hr']
            hr_source = f"configured max HR ({max_hr} bpm)"
        else:
            max_hr = max(hr_data)
            hr_source = f"peak HR in this activity ({max_hr} bpm) — tell Claude your actual max HR for accurate zones"

        lines.append(f"HR Zone distribution (based on {hr_source}):")
        lines.extend(_hr_zone_analysis(hr_data, max_hr))
        lines.append("\nHR drift (aerobic decoupling):")
        lines.extend(_hr_drift_analysis(hr_data))
    else:
        lines.append("No heart rate data available for this activity.")

    # Power zones — cycling only
    if sport == 'cycle' and 'watts' in streams:
        watts_data = [w for w in streams['watts']['data'] if w > 0]
        if watts_data:
            if 'ftp' in config:
                ftp = config['ftp']
                lines.append(f"\nPower Zone distribution (FTP: {ftp}w):")
                lines.extend(_power_zone_analysis(watts_data, ftp))
                lines.append(f"  Average power: {sum(watts_data)/len(watts_data):.0f}w")
            else:
                avg = sum(watts_data) / len(watts_data)
                lines.append(f"\nPower: avg {avg:.0f}w — tell Claude your FTP for power zone analysis.")

    # Pace/speed consistency
    if 'velocity_smooth' in streams:
        vel = [v for v in streams['velocity_smooth']['data'] if v > 0]
        if vel:
            avg_speed = sum(vel) / len(vel)
            if sport == 'cycle':
                lines.append(f"\nSpeed consistency: avg {avg_speed * 3.6:.1f} km/h")
            else:
                pace_std = (sum((v - avg_speed) ** 2 for v in vel) / len(vel)) ** 0.5
                lines.append(f"\nPace consistency:")
                lines.append(f"  Average: {_format_pace(avg_speed, sport)}")
                if pace_std > 0:
                    lines.append(f"  Range: {_format_pace(avg_speed + pace_std, sport)} – {_format_pace(avg_speed - pace_std, sport)}")

    # Cadence — sport-aware feedback
    if 'cadence' in streams:
        cad = streams['cadence']['data']
        avg_cad = sum(cad) / len(cad)
        if sport == 'cycle':
            feedback = 'good' if 85 <= avg_cad <= 100 else 'aim for 85-100 rpm for efficient pedalling'
            lines.append(f"\nCadence: {avg_cad:.0f} rpm ({feedback})")
        elif sport == 'swim':
            lines.append(f"\nStroke rate: {avg_cad:.0f} spm")
        else:
            feedback = 'good' if avg_cad >= 170 else 'consider increasing cadence towards 170-180 spm'
            lines.append(f"\nCadence: {avg_cad:.0f} spm ({feedback})")

    return '\n'.join(lines)


if __name__ == '__main__':
    mcp.run(transport="stdio")
