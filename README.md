# ADAM-Web

Internal web application for managing and reviewing personalized meal recommendations for ADAM study participants.

## Repository Structure

```
ADAM-Web/
├── backend/     # FastAPI meal plan API (see backend/README.md)
└── frontend/    # Next.js web dashboard (see frontend/README.md)
```

## Docker Quick Start

Copy the example environment file and fill in the real values:

```bash
cp .env.example .env
```

Run the full local development stack:

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml up --build
```

This starts:

- `frontend` on [http://localhost:3000](http://localhost:3000)
- `backend` on [http://localhost:8000](http://localhost:8000)
- `redis` on `localhost:6379`
- `plan-worker` for meal-plan jobs

Watch logs:

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml logs -f backend plan-worker frontend
```

## Production Backend

The production server only needs to run the backend stack because the frontend is hosted on Vercel:

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build
```

This starts:

- `backend` bound to `127.0.0.1:8000` for Nginx
- `plan-worker`
- `redis` with persistent storage

Nginx should proxy the public backend URL to `http://127.0.0.1:8000`.

Server `.env` should include production values:

```env
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_SERVICE_KEY=your_service_role_key
SUPABASE_JWT_SECRET=your_supabase_jwt_secret
ALLOWED_ORIGINS=https://adam.vercel.app
```

Vercel should include:

```env
BACKEND_URL=https://datatools.sjri.res.in/ADAM
NEXT_PUBLIC_SUPABASE_URL=https://your-project.supabase.co
NEXT_PUBLIC_SUPABASE_ANON_KEY=your_supabase_anon_key
```

## Manual Quick Start

### 1. Backend environment

Create `backend/.env`:

```env
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_SERVICE_KEY=your_service_role_key
```

> Use the **service role key** (not the anon key) so the backend can bypass Row Level Security.

Install and run:

```bash
cd backend
python -m venv .adam
source .adam/bin/activate      # Windows: .adam\Scripts\activate
pip install -r requirements.txt
uvicorn main:app --reload --port 8000
```

### 2. Frontend environment


Create `frontend/.env.local`:
```env
NEXT_PUBLIC_SUPABASE_URL=https://your-project.supabase.co
NEXT_PUBLIC_SUPABASE_ANON_KEY=your_supabase_anon_key
BACKEND_URL=http://localhost:8000
```

> Use the **anon key** here — the frontend runs in the browser and relies on Supabase Auth + RLS for security.

Install and run:

```bash
cd frontend
npm install
npm run dev
```

Open [http://localhost:3000](http://localhost:3000).

## Backend

FastAPI service that generates 7-day personalised meal plans using a PuLP LP solver and writes them to Supabase. See [backend/README.md](backend/README.md) for full details.

## Frontend

Next.js web dashboard for participant onboarding and personalised meal plan viewing. See [frontend/README.md](frontend/README.md) for full details.



