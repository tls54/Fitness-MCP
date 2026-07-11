FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY garmin_tools.py strava_tools.py oauth_provider.py main.py exercise_db.py exercises.db ./

CMD ["python", "main.py"]
