FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends gcc ffmpeg \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY src/ ./src/
COPY main.py .

RUN mkdir -p /app/logs /app/uploads/voice /app/personal_data \
    && chmod 700 /app/personal_data

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app \
    PERSONAL_DATA_DIR=/app/personal_data

CMD ["python", "main.py", "telegram"]
