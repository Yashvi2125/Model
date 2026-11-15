# TripMate AI — Multi-Agent Group Trip Planner

A full-stack collaborative travel planning application: shared group chat, AI preference extraction, conflict detection with automated compromises, day-by-day AI itineraries, real-time budget arithmetic, and collaborative checklists.

Built with **React 18 + TypeScript + Vite + Tailwind CSS** (Frontend) and **FastAPI + SQLAlchemy + Google Gemini + AutoGen** (Backend).

---

## ⚡ Quick Start for Teammates (Zero Config — No Docker Required)

If you are cloning this repository to run locally:

### Option 1: One-Click Windows Launcher
1. Clone the repository:
   ```bash
   git clone https://github.com/Yashvi2125/multi_agent_trip_planner.git
   cd multi_agent_trip_planner
   ```
2. Double-click **`run_app.bat`** (or run `.\run_app.bat` in command prompt).
   - Automatically sets up Python virtualenv, installs dependencies, and creates the database.
   - Automatically opens the web app at **http://localhost:5173**.
   - Backend runs on **http://localhost:8000**.

### Option 2: Manual Start (PowerShell / Terminal)
1. Copy `.env.example` to `.env`:
   ```powershell
   Copy-Item .env.example .env
   ```
   Add your `GEMINI_API_KEY` in `.env` (free from [Google AI Studio](https://aistudio.google.com/)).
2. Start the Backend (Terminal 1):
   ```powershell
   .\start_dev.ps1
   ```
   *Tables and SQLite database are auto-created on startup! Login, Signup, and Joining trips work immediately.*
3. Start the Frontend (Terminal 2):
   ```powershell
   .\start_frontend.ps1
   ```
4. Open your browser at **http://localhost:5173**.

---

## 🐳 Run with Docker Compose

If you have Docker Desktop installed:
1. Copy `.env.example` to `.env` and fill in `GEMINI_API_KEY`.
2. Start all containers:
   ```bash
   docker compose up --build
   ```
3. Open:
   - **Frontend:** http://localhost:3000
   - **Backend API:** http://localhost:8000
   - **API Docs (Swagger):** http://localhost:8000/api/docs

---

## 🚀 Cloud Deployment (Render / Vercel / GitHub Pages)

### Why GitHub Pages Alone Cannot Run Full-Stack Apps:
GitHub Pages only hosts static files (HTML/CSS/JS). It **cannot** run Python code, FastAPI servers, PostgreSQL/SQLite databases, or WebSockets. If you host the frontend on GitHub Pages without a backend, all API calls (login, signup, trips, chat) fail with 404 errors.

### Complete Free Cloud Hosting Options:

#### Option A: Deploy Full Stack on Render (Free, Recommended)
Render hosts Python FastAPI + PostgreSQL + WebSockets for free:
1. Fork or push this repository to GitHub.
2. Sign in to [Render.com](https://render.com/).
3. Click **New +** > **Blueprint** and select your repository.
4. Render automatically reads `render.yaml` to deploy:
   - PostgreSQL Database
   - FastAPI Backend with WebSockets and Gemini AI
5. Set `GEMINI_API_KEY` in Render Environment Variables.

#### Option B: Frontend on Vercel + Backend on Render
1. Deploy Backend on Render as above (gives you a URL like `https://tripmate-backend.onrender.com`).
2. Go to [Vercel](https://vercel.com/) > **Add New Project** > select this repo.
3. Set **Root Directory** to `frontend`.
4. Add Environment Variable:
   - `VITE_API_BASE`: `https://tripmate-backend.onrender.com`
5. Click **Deploy**. Vercel will give you a live URL like `https://multi-agent-trip-planner.vercel.app`.

#### Option C: Frontend on GitHub Pages
This repo includes `.github/workflows/deploy-pages.yml`:
1. In your GitHub repo, go to **Settings** > **Pages** > Source: **GitHub Actions**.
2. Go to **Settings** > **Secrets and variables** > **Actions** > add secret:
   - `VITE_API_BASE`: your deployed backend URL (from Render/Railway).
3. Push to `main` branch. GitHub Actions will build and deploy to:
   `https://yashvi2125.github.io/multi_agent_trip_planner/`

---

## 👥 How Multiple Users / Teammates Collaborate

When running locally on different computers:
- Each person running `localhost` has their own separate local database.
- To join the **same trip** (e.g. Yashvi's trip with code `4VSE4K9Y`), both users must connect to the **same backend server**:
  1. Either deploy the backend online (Option A/B above), OR
  2. The trip organiser shares their local backend using a tunnel like **ngrok** (`ngrok http 8000`).

---

## 🧩 Key Architecture

| Module | Purpose |
|---|---|
| `agents/` | AutoGen Planner and Researcher travel team |
| `server/routers/auth.py` | Secure Argon2 authentication, sessions, registration |
| `server/routers/conflicts.py` | AI conflict resolution engine & multi-user compromise generator |
| `server/routers/merge_preferences.py` | Standalone JSON preference-merging API |
| `server/services/conflicts.py` | Day-by-day scheduling & preference contradiction detection rules |
| `server/ai/client.py` | Google GenAI SDK integration with Gemini 3.1 Flash Lite |
| `frontend/src/` | React 18, Tailwind CSS, TanStack Query, Leaflet maps |
