# --- Build frontend ---
FROM node:20-slim AS webbuild
WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json* ./
RUN npm ci
COPY frontend/ .
RUN npm run build

# --- Backend image ---
FROM python:3.11-slim

# System deps: ffmpeg + build tools
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg git build-essential && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY backend/requirements.txt ./backend/requirements.txt
RUN pip install --no-cache-dir -r ./backend/requirements.txt

COPY backend ./backend
RUN mkdir -p frontend/dist
COPY --from=webbuild /app/frontend/dist ./frontend/dist

ENV PORT=8080 \
    PYTHONUNBUFFERED=1 \
    OMP_NUM_THREADS=1 \
    NUMBA_NUM_THREADS=1

CMD ["bash", "-lc", "cd backend && exec gunicorn app:app -b 0.0.0.0:${PORT} --workers 2 --threads 4 --timeout 180"]
