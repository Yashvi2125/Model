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

## 🤖 Telegram Group Bot & Google ADK Integration

TripMate AI includes a dual-interface architecture: members of the **SAME trip** can plan from a **Telegram Group** or from the **Web Chat Room**, and see each other's messages, preferences, and the same generated plan synchronized in real time!

### 🌟 Features
1. **Google ADK Travel Advisor Agent (`google-adk`)**: Powered by Gemini API with multi-turn conversational memory via ADK `SessionService`.
2. **Platform Independence**: Web and Telegram users collaborate simultaneously with two-way message relay, Telegram badges on web UI, and shared trip state.
3. **Rich Telegraph Itineraries (`telegra.ph`)**: Long itineraries are formatted and auto-published to clean, shareable Telegraph pages with inline buttons.
4. **Passive Preference Extraction**: Quietly listens to natural conversation in the group to infer member travel preferences without spamming.
5. **Interactive Controls**: Inline buttons to Approve plans, view budget breakdowns, and jump directly to the Web Dashboard.

---

### ⚙️ Bot Setup Guide with @BotFather

1. **Create the Bot:**
   - Open Telegram and message [@BotFather](https://t.me/BotFather).
   - Send `/newbot`, name your bot (e.g., `TripMate AI`), and choose a username (e.g., `Tripmate_planner_bot`).
   - Copy the HTTP API token into `.env` under `TELEGRAM_BOT_TOKEN`.

2. **IMPORTANT: Disable Group Privacy Mode:**
   - In [@BotFather](https://t.me/BotFather), send `/setprivacy`.
   - Select your bot (`@Tripmate_planner_bot`).
   - Choose **Disable**.
   - *(Why? Telegram restricts bots to seeing only messages that mention them unless privacy mode is disabled. Disabling it allows TripMate AI to passively read preferences from the group conversation).*

3. **Add Bot to Group:**
   - Add `@Tripmate_planner_bot` to your trip group.

---

### 💬 Telegram Commands

| Command | Description |
| :--- | :--- |
| `/start` | Welcome overview. With deep-link (`/start <CODE>`), instantly joins that trip. |
| `/newtrip <destination>` | Creates a new trip, generates a Trip Code, and binds the Telegram group. |
| `/jointrip <CODE>` | Connects this Telegram group to an existing trip (e.g. created on the web). |
| `/plan [notes]` | Triggers the collaborative multi-agent workflow (Planner + Researcher). |
| `/itinerary` | Displays the latest itinerary, Telegraph article link, and web buttons. |
| `/budget` | Computes estimated costs and per-person breakdown. |
| `/status` | Overview of collected member preferences, open conflicts, and readiness. |
| `/members` | Lists all group members (with indicators for Web vs Telegram). |
| `/weblink` | Direct link to view and edit the trip in the Web Dashboard. |
| Natural chat / `@ai` | Chat naturally with the Google ADK Travel Advisor Agent with live typing actions. |

---

### 🛠 Running Locally vs. Production Deployment

#### Local Development (Long-Polling Mode — Default)
In `.env`:
```env
TELEGRAM_MODE=polling
TELEGRAM_BOT_TOKEN=your_bot_token
TELEGRAM_BOT_USERNAME=Tripmate_planner_bot
PUBLIC_BASE_URL=http://localhost:3000
```
Start the backend via `.\start_dev.ps1` or `run_app.bat`. The bot connects via long-polling immediately with zero tunnel required!

#### Production Deployment (Webhook Mode)
In production, the bot operates in webhook mode for high efficiency, receiving push updates from Telegram at `/api/telegram/webhook`.
When `TELEGRAM_MODE=webhook`, the backend automatically registers the webhook with Telegram on startup using `TELEGRAM_WEBHOOK_URL` and `TELEGRAM_WEBHOOK_SECRET`.

---

## 🚀 Deployment Guide (Supabase + Render)

### 1. Database: Supabase PostgreSQL
1. Create a project at [supabase.com](https://supabase.com/).
2. Under **Project Settings > Database > Connection string**, copy the **Session pooler** URI (port `5432`, not transaction pooler `6543`) with mode `sslmode=require`:
   ```
   postgresql+psycopg://postgres.[ref]:[password]@aws-0-[region].pooler.supabase.com:5432/postgres?sslmode=require
   ```
3. To transfer your local data into Supabase:
   ```bash
   docker compose exec -T db pg_dump -U tripmate -d tripmate --clean --if-exists --no-owner --no-privileges --encoding=UTF8 > backup.sql
   psql "<supabase-session-pooler-uri>" < backup.sql
   ```

### 2. Telegram Bot Configuration (BotFather)
1. Open [@BotFather](https://t.me/BotFather) on Telegram.
2. Ensure group privacy is disabled so the bot can read trip chat messages:
   - Run `/setprivacy` -> Select `@Tripmate_planner_bot` -> Select **Disable**.
3. (Optional) Set group permissions:
   - Run `/setjoingroups` -> Select **Enable**.

### 3. Deploying to Render
1. Connect your GitHub repository on [Render](https://render.com/).
2. Render detects `render.yaml` (Blueprint) and provisions two services:
   - **`tripmate-backend`** (Web Service, Docker runtime, 1 instance)
   - **`tripmate-frontend`** (Static Site, React SPA with rewrite `/* -> /index.html`)
3. Set the environment variables in the Render dashboard:
   - **Backend:**
     - `DATABASE_URL`: Your Supabase session pooler connection string.
     - `SECRET_KEY`: Random 64-char string (`openssl rand -hex 32`).
     - `ALLOWED_ORIGINS`: `https://<your-frontend>.onrender.com`.
     - `PUBLIC_BASE_URL`: `https://<your-frontend>.onrender.com`.
     - `TELEGRAM_WEBHOOK_URL`: `https://<your-backend>.onrender.com`.
     - `TELEGRAM_WEBHOOK_SECRET`: Random 32-char string (`openssl rand -hex 16`).
     - `TELEGRAM_BOT_TOKEN`, `GEMINI_API_KEY`, `TAVILY_API_KEY`.
   - **Frontend:**
     - `VITE_API_BASE`: `https://<your-backend>.onrender.com`.
4. Deploy! The backend automatically runs database migrations (`alembic upgrade head`) and registers the Telegram webhook on startup.

---

### 🎬 Interactive Demo Walkthrough
1. **Web User:** Creates a trip *"Kyoto Expedition"* on `http://localhost:3000` (Trip Code: `KYOT8888`).
2. **Telegram User:** In a Telegram group, types `/jointrip KYOT8888`.
   - Bot replies: *"Connected to Kyoto Expedition! All group messages will now sync with the web planner."*
3. **Collaboration:**
   - Tanish in Telegram: *"I really want to visit Fushimi Inari and eat ramen."*
   - Yashvi on Web: Sees the message live in chat marked with a **[Telegram]** badge.
   - Yashvi replies on Web: *"Sounds awesome! Let's also visit Arashiyama Bamboo Grove."*
   - The message instantly relays into the Telegram group: *"Yashvi (via web): Sounds awesome! Let's also visit Arashiyama Bamboo Grove."*
4. **Planning:**
   - Type `/plan` in Telegram or click *"Generate Itinerary"* on the web.
   - The agents research live attractions, synthesize the itinerary, update the Web dashboard, and post the formatted plan in Telegram with a clean [Telegraph article link](https://telegra.ph) and approval buttons!

---

## 🧪 Running Automated Tests

TripMate includes an isolated, safe test suite with built-in database protection guards.

### Running in Docker (PostgreSQL)
Tests automatically detect PostgreSQL and use a separate, dedicated `tripmate_test` database (auto-created if missing). Your live `tripmate` database data is never touched:
```bash
docker compose exec backend pytest tests/web/
```

### Running Locally (SQLite)
Without Docker or Postgres, tests automatically run against an isolated temporary SQLite database:
```bash
pytest tests/web/
```

### 🛡️ Database Safety Guard
The test runner includes an automated hard guard (`tests/db_guard.py`):
1. **Name Check:** Verifies that the test database name ends with `_test`.
2. **Anti-Collision Check:** Confirms the test database does not equal the live `DATABASE_URL` database.
3. **Pre-Drop Verification:** Right before `Base.metadata.drop_all()`, the fixture verifies the active SQLAlchemy engine connection. If any check fails, the runner aborts with a `RuntimeError` before any table or row can be touched.

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
