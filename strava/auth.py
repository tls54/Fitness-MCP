import os
import json
from dotenv import load_dotenv
import requests
import webbrowser
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
TOKEN_FILE = os.path.join(BASE_DIR, 'strava_token.json')

captured_code = None

def build_strava_oauth_url() -> str:
    id = os.environ.get('STRAVA_CLIENT_ID')
    return f'https://www.strava.com/oauth/authorize?client_id={id}&redirect_uri=http://localhost:8000/callback&response_type=code&scope=activity:read_all'


def save_tokens(tokens) -> None:
    data = {
        'access_token': tokens['access_token'],
        'refresh_token': tokens['refresh_token'],
        'expires_at': tokens['expires_at']
    }
    with open(TOKEN_FILE, 'w') as f:
        json.dump(data, f)


class CallbackHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        global captured_code
        params = parse_qs(urlparse(self.path).query)
        captured_code = params['code'][0]
        # Send a response so the browser doesn't hang
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b'Auth complete. You can close this tab.')



if __name__ == '__main__':
    load_dotenv()

    build_strava_oauth_url_string = build_strava_oauth_url()

    webbrowser.open(build_strava_oauth_url_string)

    server = HTTPServer(('localhost', 8000), CallbackHandler)
    server.handle_request()  # handles exactly ONE request then returns

    response = requests.post('https://www.strava.com/oauth/token', data={
        'client_id': os.environ.get('STRAVA_CLIENT_ID'),
        'client_secret': os.environ.get('STRAVA_CLIENT_SECRET'),
        'code': captured_code,
        'grant_type': 'authorization_code'
    })
    tokens = response.json()

    save_tokens(tokens)