FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq5 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app.py .

ENV HOST=0.0.0.0 \
    PORT=8000 \
    DATABASE_URL=postgresql://postgres:postgres@localhost:5432/url_shortener \
    REDIS_URL=redis://localhost:6379/0 \
    JWT_SECRET_KEY=dev-secret-change-me \
    INACTIVE_DELETE_DAYS=30

EXPOSE 8000

CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]