# ADAM-Web

Internal web application for managing and reviewing personalized meal recommendations for ADAM study participants.

## Repository Structure
```
ADAM-Web/
├── backend/     # FastAPI meal plan API (see backend/README.md)
├── frontend/    # Next.js web dashboard (see frontend/README.md)
└── .adam/       # Python virtual environment
```

## Backend
The API is built with FastAPI and Python. It generates 7-day meal plans using a PuLP LP solver and writes them to Supabase. See [backend/README.md](backend/README.md) for setup and development instructions.

## Frontend
The web dashboard is built with Next.js, Supabase, and Tailwind CSS. See [frontend/README.md](frontend/README.md) for setup and development instructions.




