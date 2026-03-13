# ADAM-Web

Internal web application for managing and reviewing personalized meal recommendations for ADAM study participants.

## Repository Structure

```
ADAM-Web/
├── backend/     # FastAPI meal plan API (see backend/README.md)
└── frontend/    # Next.js web dashboard (see frontend/README.md)
```

## Quick Start

### 1. Backend environment

Create `backend/.env`:

copy the credentials from env.example to env 

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
copy credentials from env_example.txt
```env
NEXT_PUBLIC_SUPABASE_URL=https://your-project.supabase.co
NEXT_PUBLIC_SUPABASE_ANON_KEY=your_supabase_anon_key
NEXT_PUBLIC_BACKEND_URL=http://localhost:8000
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






