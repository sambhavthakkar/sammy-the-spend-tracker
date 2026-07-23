# BudgetBot — API or Telegram worker
FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
    || pip install --no-cache-dir \
        flask sqlalchemy python-dotenv python-json-logger httpx \
        requests python-dateutil python-telegram-bot faster-whisper gunicorn

COPY src/ ./src/
COPY main.py .
COPY .env.example .

RUN mkdir -p logs uploads/voice

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app

EXPOSE 5000

# Default: API. Override for telegram: python main.py telegram
CMD ["python", "main.py", "api"]
