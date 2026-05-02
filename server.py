import os
import json
import requests
from datetime import datetime
from dotenv import load_dotenv
from time import time
from mcp.server.fastmcp import FastMCP



BASE_DIR = os.path.dirname(os.path.abspath(__file__))
TOKEN_FILE = os.path.join(BASE_DIR, 'strava_token.json')



def check_expired_token(expiry):
    current_time = time()
    if current_time > expiry:
        return True
    else:
        return False


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
    new_tokens = response.json()

    save_tokens(new_tokens)


def validate_strava_token():
    with open(TOKEN_FILE) as f:
        tokens = json.load(f)

    if check_expired_token(tokens['expires_at']):
        refresh_strava_tokens(tokens)
        with open(TOKEN_FILE) as f:  # reload after refresh
            tokens = json.load(f)
    return tokens['access_token']


def format_seconds(seconds: int) -> str:
    seconds = int(seconds)
    h = seconds // 3600
    m = (seconds % 3600) // 60
    s = seconds % 60
    return f"{h}:{m:02d}:{s:02d}"


load_dotenv()
ACCESS_TOKEN = validate_strava_token()

mcp = FastMCP(
    "strava",
    instructions=(
        "You have access to the user's real Strava training data via these tools. "
        "Always use these tools when the user asks anything about their runs, workouts, training, pace, distance, fitness, or athletic performance — "
        "never answer from memory or make up data. "
        "Today's date is " + datetime.now().strftime("%Y-%m-%d") + "."
    )
)

METRIC_CONFIG = {
    'pace':      {'key': lambda a: a.get('average_speed', 0),  'reverse': False, 'filter': lambda a: a.get('average_speed', 0) > 0},
    'distance':  {'key': lambda a: a.get('distance', 0),       'reverse': True,  'filter': lambda a: a.get('distance', 0) > 0},
    'time':      {'key': lambda a: a.get('moving_time', 0),    'reverse': True,  'filter': lambda a: True},
    'elevation': {'key': lambda a: a.get('total_elevation_gain', 0), 'reverse': True, 'filter': lambda a: True},
}


@mcp.tool()
def ping() -> str:
    '''
    This is the test ping function. Use it to verify the server is running.
    Input: None
    returns: str(Pong)
    '''
    return f"pong — token: {ACCESS_TOKEN[:6]}..."


@mcp.tool()
def get_athlete_stats() -> str:
    """Returns the athlete's running stats: recent (4-week), YTD, and all-time totals for distance, time, elevation, and run count. Always use this when the user asks about their overall training volume, yearly mileage, or fitness summary."""

    athelete_response = requests.get('https://www.strava.com/api/v3/athlete', headers={
        'Authorization': f'Bearer {ACCESS_TOKEN}'
        })
    
    athelete = athelete_response.json()
    
    athelete_stats_response = requests.get(f'https://www.strava.com/api/v3/athletes/{athelete["id"]}/stats', headers={
        'Authorization': f'Bearer {ACCESS_TOKEN}'
        })
    stats = athelete_stats_response.json()

    return f'''
    Recent (4 weeks):
    Distance: {(stats['recent_run_totals']['distance'] / 1000):.2f} km
    Time: {format_seconds(stats['recent_run_totals']['moving_time'])}
    Elevation: {stats['recent_run_totals']['elevation_gain']} m
    Runs: {stats['recent_run_totals']['count']}

    YTD ({datetime.now().strftime("%-d %B %Y")}):
    Distance: {(stats['ytd_run_totals']['distance'] / 1000):.2f} km
    Time: {format_seconds(stats['ytd_run_totals']['moving_time'])}
    Elevation: {stats['ytd_run_totals']['elevation_gain']} m
    Runs: {stats['ytd_run_totals']['count']}

    All runs total:
    Distance: {(stats['all_run_totals']['distance'] / 1000):.2f} km
    Time: {format_seconds(stats['all_run_totals']['moving_time'])}
    Elevation: {stats['all_run_totals']['elevation_gain']} m
    Runs: {stats['all_run_totals']['count']}
    '''


def _format_pace(speed_ms: float) -> str:
    if not speed_ms:
        return 'N/A'
    pace_secs = int(1000 / speed_ms)
    return f"{pace_secs // 60}:{pace_secs % 60:02d} /km"


def _format_date(date_str: str) -> str:
    return datetime.strptime(date_str, "%Y-%m-%dT%H:%M:%SZ").strftime("%Y-%m-%d %H:%M")


def _format_activity(a: dict) -> str:
    lines = [
        f"  [{a['id']}] {a['name']} ({a.get('type', 'Unknown')}) — {_format_date(a['start_date_local'])}",
        f"  Distance: {a['distance'] / 1000:.2f} km | Time: {format_seconds(a['moving_time'])} | Pace: {_format_pace(a.get('average_speed', 0))}",
        f"  Elevation: {a['total_elevation_gain']} m",
    ]
    if a.get('average_heartrate'):
        lines.append(f"  HR: avg {a['average_heartrate']:.0f} bpm / max {a.get('max_heartrate', 'N/A'):.0f} bpm")
    if a.get('average_cadence'):
        lines.append(f"  Cadence: {a['average_cadence']:.0f} spm")
    if a.get('suffer_score'):
        lines.append(f"  Suffer score: {a['suffer_score']}")
    return '\n'.join(lines)


@mcp.tool()
def get_recent_activities(count: int = 10, after: str = None, before: str = None) -> str:
    """Returns the athlete's activities. Always use this when the user asks about specific runs, recent workouts, or training on a particular date. Returns activity IDs which can be passed to get_activity_detail.
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
    response = requests.get(
        'https://www.strava.com/api/v3/athlete/activities',
        headers=headers,
        params=params
    )
    activities = response.json()
    if not activities:
        return "No activities found."
    blocks = [_format_activity(a) for a in activities]
    return f"{len(activities)} activities found:\n\n" + '\n\n'.join(blocks)


@mcp.tool()
def get_activity_detail(activity_id: int) -> str:
    """Returns full detail for a single activity including km splits, heart rate, cadence, and perceived exertion. Always use this when the user wants to analyse a specific workout in depth. Get the activity_id from get_recent_activities first."""
    headers = {'Authorization': f'Bearer {ACCESS_TOKEN}'}
    response = requests.get(f'https://www.strava.com/api/v3/activities/{activity_id}', headers=headers)
    if response.status_code == 404:
        return f"Activity {activity_id} not found."
    a = response.json()

    lines = [
        f"{a['name']} ({a.get('type', 'Unknown')}) — {_format_date(a['start_date_local'])}",
        f"Distance: {a['distance'] / 1000:.2f} km | Time: {format_seconds(a['moving_time'])} | Pace: {_format_pace(a.get('average_speed', 0))}",
        f"Elevation: {a['total_elevation_gain']} m",
    ]
    if a.get('description'):
        lines.append(f"Description: {a['description']}")
    if a.get('average_heartrate'):
        lines.append(f"HR: avg {a['average_heartrate']:.0f} bpm / max {a.get('max_heartrate', 'N/A'):.0f} bpm")
    if a.get('average_cadence'):
        lines.append(f"Cadence: {a['average_cadence']:.0f} spm")
    if a.get('suffer_score'):
        lines.append(f"Suffer score: {a['suffer_score']}")
    if a.get('perceived_exertion'):
        lines.append(f"Perceived exertion: {a['perceived_exertion']}")
    if a.get('calories'):
        lines.append(f"Calories: {a['calories']}")
    if a.get('device_name'):
        lines.append(f"Device: {a['device_name']}")

    if a.get('splits_metric'):
        lines.append("\nKm splits:")
        for split in a['splits_metric']:
            pace = _format_pace(split.get('average_speed', 0))
            hr = f" | HR {split['average_heartrate']:.0f}" if split.get('average_heartrate') else ''
            elev = f" | elev {split['elevation_difference']:+.0f}m" if split.get('elevation_difference') else ''
            lines.append(f"  km {split['split']}: {pace}{hr}{elev}")

    return '\n'.join(lines)


@mcp.tool()
def get_best_activities(metric: str = "pace", top_n: int = 5, activity_type: str = "Run") -> str:
    """Returns the athlete's best activities ranked by a metric. Always use this when the user asks about their fastest, longest, hardest, or highest-elevation workouts.
    metric: one of 'pace' (fastest), 'distance' (longest), 'time' (longest duration), 'elevation' (most climb).
    top_n: how many results to return (default 5).
    activity_type: filter by type e.g. 'Run', 'TrailRun', 'Hike' (default 'Run').
    """
    if metric not in METRIC_CONFIG:
        return f"Unknown metric '{metric}'. Choose from: {', '.join(METRIC_CONFIG.keys())}."

    headers = {'Authorization': f'Bearer {ACCESS_TOKEN}'}
    response = requests.get(
        'https://www.strava.com/api/v3/athlete/activities',
        headers=headers,
        params={'per_page': 200}
    )
    all_activities = response.json()

    filtered = [a for a in all_activities if a.get('type') == activity_type or a.get('sport_type') == activity_type]
    config = METRIC_CONFIG[metric]
    filtered = [a for a in filtered if config['filter'](a)]
    ranked = sorted(filtered, key=config['key'], reverse=config['reverse'])[:top_n]

    if not ranked:
        return f"No {activity_type} activities found."

    label = {'pace': 'fastest', 'distance': 'longest', 'time': 'longest by time', 'elevation': 'most elevation'}[metric]
    lines = [f"Top {len(ranked)} {label} {activity_type.lower()}s:\n"]
    for i, a in enumerate(ranked, 1):
        if metric == 'pace':
            stat = f"Pace: {_format_pace(a.get('average_speed', 0))}"
        elif metric == 'distance':
            stat = f"Distance: {a['distance'] / 1000:.2f} km"
        elif metric == 'time':
            stat = f"Time: {format_seconds(a['moving_time'])}"
        else:
            stat = f"Elevation: {a['total_elevation_gain']} m"
        lines.append(f"{i}. [{a['id']}] {a['name']} — {_format_date(a['start_date_local'])} | {stat}")

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


@mcp.tool()
def get_activity_streams(activity_id: int, stream_types: str = "heartrate,velocity_smooth,cadence,altitude") -> str:
    """Returns raw time-series data for an activity — one data point per second for HR, pace, cadence, and altitude.
    Use this when the user wants to see exactly how a metric changed over the course of a workout, e.g. 'show me my HR trace' or 'how did my pace change throughout the run'.
    For summary insights (zone distribution, HR drift, effort quality) use get_activity_analysis instead.
    stream_types: comma-separated list of streams to fetch (default: heartrate,velocity_smooth,cadence,altitude).
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
        elif stream_type == 'cadence':
            lines.append(f"Cadence (spm): min {min(data)}, max {max(data)}, avg {sum(data)/len(data):.0f}")
        elif stream_type == 'altitude':
            lines.append(f"Altitude (m): min {min(data):.0f}, max {max(data):.0f}")

    return '\n'.join(lines)


@mcp.tool()
def get_activity_analysis(activity_id: int) -> str:
    """Returns a structured training analysis for an activity — HR zone distribution, aerobic decoupling, pace-HR correlation, and cadence consistency.
    Use this when the user wants to understand the quality of a workout, e.g. 'how was my aerobic effort?', 'was I in zone 2?', 'did my HR drift during the run?'.
    For raw second-by-second data use get_activity_streams instead.
    """
    streams = _fetch_streams(activity_id, ['heartrate', 'velocity_smooth', 'cadence', 'time'])
    if not streams or 'heartrate' not in streams:
        return f"No heart rate data available for activity {activity_id}."

    hr_data = streams['heartrate']['data']
    total = len(hr_data)

    # HR zones (% of max HR — using common 5-zone model with 185bpm max as a typical default)
    # Zones: Z1 <60%, Z2 60-70%, Z3 70-80%, Z4 80-90%, Z5 >90%
    max_hr = max(hr_data)
    zone_bounds = [(0, 0.60), (0.60, 0.70), (0.70, 0.80), (0.80, 0.90), (0.90, 1.01)]
    zone_counts = [sum(1 for h in hr_data if max_hr * lo <= h < max_hr * hi) for lo, hi in zone_bounds]

    lines = [f"Training analysis for activity {activity_id}:\n"]
    lines.append("HR Zone distribution (based on peak HR in this activity):")
    for i, count in enumerate(zone_counts, 1):
        bar = '█' * (count * 20 // total)
        lines.append(f"  Z{i}: {count * 100 // total:3d}%  {bar}")

    # Aerobic decoupling — compare avg HR first half vs second half at same effort
    mid = total // 2
    first_half_hr = sum(hr_data[:mid]) / mid
    second_half_hr = sum(hr_data[mid:]) / (total - mid)
    drift = (second_half_hr - first_half_hr) / first_half_hr * 100
    lines.append(f"\nHR drift (aerobic decoupling):")
    lines.append(f"  First half avg HR:  {first_half_hr:.0f} bpm")
    lines.append(f"  Second half avg HR: {second_half_hr:.0f} bpm")
    lines.append(f"  Drift: {drift:+.1f}% ({'good aerobic fitness' if abs(drift) < 5 else 'some cardiac drift — consider easier effort'})")

    # Pace consistency
    if 'velocity_smooth' in streams:
        vel = [v for v in streams['velocity_smooth']['data'] if v > 0]
        if vel:
            avg_pace = sum(vel) / len(vel)
            pace_std = (sum((v - avg_pace) ** 2 for v in vel) / len(vel)) ** 0.5
            lines.append(f"\nPace consistency:")
            lines.append(f"  Average pace: {_format_pace(avg_pace)}")
            lines.append(f"  Std deviation: {_format_pace(avg_pace - pace_std)} – {_format_pace(avg_pace + pace_std)}")

    # Cadence
    if 'cadence' in streams:
        cad = streams['cadence']['data']
        avg_cad = sum(cad) / len(cad)
        lines.append(f"\nCadence:")
        lines.append(f"  Average: {avg_cad:.0f} spm ({'good' if avg_cad >= 170 else 'consider increasing cadence towards 170-180 spm'})")

    return '\n'.join(lines)


if __name__ == '__main__':


    mcp.run(transport="stdio")