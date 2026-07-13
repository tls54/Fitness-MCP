FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY strava_tools.py oauth_provider.py main.py exercise_db.py exercises.db ./
COPY garmin ./garmin

CMD ["python", "main.py"]
