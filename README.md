# EchoMind

Split any song into separate stems (vocals, drums, bass, other) right in the browser.

Upload a track, choose your stems, and EchoMind runs it through Meta's Demucs AI model, streams progress back live, then lets you preview every stem with waveforms and play them all in sync before downloading them as a zip.

## Highlights

- AI stem separation with Demucs, plus a faster two stem mode for vocals and instrumental
- Live progress updates using server sent events
- Synced multitrack preview with per stem volume
- Accounts with email verification and password reset, weekly usage limits and Stripe payments
- Per IP rate limiting and automatic cleanup, so no audio is kept on the server
- Supports MP3, WAV, FLAC, M4A, AAC, OGG, AIFF and MP4

## Built with

| Area | Tools |
|---|---|
| Frontend | React, Vite, Tailwind CSS, wavesurfer.js |
| Backend | Python, Flask, Gunicorn |
| Audio | Demucs, PyTorch, pydub, ffmpeg |
| Data | SQLite |
| Payments | Stripe Checkout and webhooks |
| Deployment | Linux VPS, Nginx, systemd |

## How it works

1. The browser uploads the file and the backend checks the file type, length and weekly quota.
2. A background worker runs Demucs, exports 30 second MP3 previews and zips the chosen stems.
3. The browser follows the job over a server sent events stream and loads the previews when it finishes.
4. Once downloaded, or after a timeout, the job's files are deleted.

## Running locally

Requires Python 3.12, Node 18+ and ffmpeg.

```bash
# Backend
cd backend
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python db/init_db.py
cp ../.env.example ../.env   # then fill in the values
python app.py

# Frontend (new terminal)
cd frontend
npm install
cp .env.example .env
npm run dev
```

The first split downloads the Demucs model, which takes a minute.
