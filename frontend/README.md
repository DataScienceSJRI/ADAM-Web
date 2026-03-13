# ADAM Web — Frontend

Next.js web app for ADAM study participants to complete onboarding and view personalised meal recommendations.

## Tech Stack

- **Framework:** Next.js 16 (App Router)
- **Language:** TypeScript
- **Styling:** Tailwind CSS v4
- **UI Components:** shadcn/ui (Radix UI primitives)
- **Auth / DB:** Supabase
- **Icons:** Lucide React
- **Theme:** next-themes (light/dark mode)

## Project Structure

```
src/
├── app/
│   ├── layout.tsx                      # Root layout with theme provider
│   ├── page.tsx                        # Redirects to /dashboard
│   ├── login/
│   │   └── page.tsx                    # Email + password sign-in
│   ├── onboarding/
│   │   └── page.tsx                    # Multi-step onboarding flow
│   └── dashboard/
│       ├── layout.tsx                  # Dashboard layout with sidebar
│       ├── page.tsx                    # Dashboard home
│       └── recommendations/
│           └── page.tsx                # Personalised meal plan viewer
├── components/
│   ├── ui/                             # shadcn/ui base components
│   ├── app-sidebar.tsx                 # Navigation sidebar
│   ├── basic-details-form.tsx          # Onboarding step 1 — demographics
│   ├── meal-preferences-form.tsx       # Onboarding step 2 — meal preferences
│   ├── meal-card.tsx                   # Meal recommendation card
│   ├── meal-plan-table.tsx             # Weekly meal plan table with comments
│   ├── health-stats-card.tsx           # Health stats display
│   ├── user-nav.tsx                    # User avatar / sign-out menu
│   ├── theme-toggle.tsx                # Light/dark mode toggle
│   └── theme-provider.tsx             # Theme context wrapper
├── lib/
│   ├── utils.ts                        # Tailwind class utilities
│   └── supabase/
│       ├── client.ts                   # Supabase browser client
│       └── server.ts                   # Supabase server client
└── hooks/
    └── use-mobile.ts                   # Mobile viewport detection hook
```

## Getting Started

### Prerequisites

- Node.js 18+
- A Supabase project with the required tables
- The ADAM backend running (see `backend/README.md`)

### Installation

```bash
cd frontend
npm install
```

### Environment Variables

Create a `.env.local` file in the `frontend/` directory:

```env
NEXT_PUBLIC_SUPABASE_URL=https://your-project.supabase.co
NEXT_PUBLIC_SUPABASE_ANON_KEY=your_supabase_anon_key
NEXT_PUBLIC_BACKEND_URL=http://localhost:8000
```

### Development

```bash
npm run dev
```

Open [http://localhost:3000](http://localhost:3000). Unauthenticated users are redirected to `/login`.

### Build

```bash
npm run build
npm run start
```

## Pages

| Route | Description |
|-------|-------------|
| `/login` | Email/password sign-in via Supabase Auth |
| `/onboarding` | Multi-step onboarding: demographics → meal preferences |
| `/dashboard` | Dashboard home |
| `/dashboard/recommendations` | Personalised 7-day meal plan viewer with plan history |

## Key Features

### Onboarding (`/onboarding`)
- **Step 1** — Basic details: Age, Gender, Weight, Height, HbA1c, Activity level, Diet restrictions → writes to `BE_Basic_Details` + `BE_Preference_onboarding_details`
- **Step 2** — Meal preferences: subcategory selection per meal time → writes to `BE_Preference_onboarding`

### Recommendations (`/dashboard/recommendations`)
- Calls `POST /plan` on the backend to generate a 7-day meal plan
- Displays meals grouped by date and meal time (Breakfast / Lunch / Dinner / Snacks)
- **Plan history** — each generation creates a new plan with a unique `plan_id`; older plans are accessible via the "Plan history" selector
- **Per-item reactions** — thumbs up/down on individual food items (saved to `Recommendation.Reaction`)
- **Combo reactions** — rate the full meal slot combination (saved to `Recommendation.Combo_Reaction`)
- **Daily notes** — free-text comment per day (saved to `UserComments`)
- Disliked recipes are excluded from future plan generations

## Database Tables

| Table | Used by frontend |
|-------|-----------------|
| `BE_Basic_Details` | Written during onboarding step 1 |
| `BE_Preference_onboarding` | Written during onboarding step 2; reactions updated from recommendations page |
| `BE_Preference_onboarding_details` | Written during onboarding step 1 |
| `Recommendation` | Read/written by recommendations page (`plan_id`, `Reaction`, `Combo_Reaction`) |
| `UserComments` | Daily notes attached to meal plan dates |
| `SubCategory_Onboarding` | Read during onboarding step 2 to populate preference options |

## Authentication

Handled by Supabase Auth. The middleware at `src/middleware.ts` refreshes the session on every request. The frontend uses `user.email` as the `user_id` identifier in all Supabase table queries (matching the backend's identifier).
