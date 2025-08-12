
# EchoMind - Running & Testing Guide

## 🚀 Running the Application (Development)
1. **Activate your virtual environment**:
   ```bash
   # Windows
   venv\Scripts\activate
   # Mac/Linux
   source venv/bin/activate
   ```

2. **Start the Flask backend**:
   ```bash
   cd backend
   python app.py
   ```

3. **Start the React frontend**:
   ```bash
   cd frontend
   npm run dev
   ```

4. **Open your browser at the React URL** (usually):
   ```
   http://localhost:5173
   ```

✅ React handles the UI, Flask handles API routes (`/upload`, `/stream/<job_id>`, `/download/<job_id>`). Both must run at the same time in development.

---

## ✅ Running Automated Tests (Backend)
1. **Enable Test Mode**:
   ```powershell
   # Windows PowerShell
   set ECHO_TEST_MODE=1
   # Mac/Linux
   export ECHO_TEST_MODE=1
   ```

2. **Start the backend in test mode**:
   ```bash
   python app.py
   ```

3. **In another terminal, run the tester**:
   ```bash
   python tests/test_backend_v2.py
   ```

4. **View reports** in `tests/reports/`.

---

## 🛠 Deployment (Production)
1. **Install backend dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

2. **Build React frontend**:
   ```bash
   cd frontend
   npm run build
   ```

3. **Serve built files with Flask or Nginx**:
   - Copy `frontend/dist` into a static folder or configure Flask to serve it.
   - Start backend with Gunicorn:
     ```bash
     gunicorn -w 4 app:app
     ```

4. (Optional) Use Nginx as a reverse proxy for SSL and static assets.

---

## 📂 Project Structure
```
EchoMind/
  backend/
    app.py              # Main Flask backend
    audio_splitter.py   # Demucs audio splitting logic
    requirements.txt    # Backend dependencies
    logs/               # Backend logs (contents ignored in snapshots)
    temp/               # Temporary job files
    uploads/            # Uploaded files
  frontend/
    index.html          # Vite React entry point
    package.json        # Frontend dependencies
    tailwind.config.js  # Tailwind setup
    src/
      api.js            # Axios API calls
      App.jsx           # Main React component/UI logic
      main.jsx          # React entry point
      index.css         # Global styles
  tests/
    test_backend_v2.py  # Automated backend tester
    reports/            # Test reports (contents ignored in snapshots)
```

---

## 🔑 Notes:
- `@cross_origin()` is enabled on `/upload`, `/stream`, `/download` routes for React ↔ Flask communication.
- React URL (`localhost:5173`) and Flask URL (`127.0.0.1:5000`) must both be running during development.
- For production, React is built and served from Flask or a reverse proxy like Nginx.
- `logs/`, `temp/`, and `tests/reports/` are kept for context but their file contents are ignored in snapshots.
