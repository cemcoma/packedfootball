# Build from the repo root: docker build -f backend/Dockerfile .
FROM python:3.12-slim

WORKDIR /app
COPY backend/requirements.txt backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt

COPY packedfootball/ packedfootball/
COPY backend/ backend/

WORKDIR /app/backend
ENV PORT=8080
CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port ${PORT}"]
