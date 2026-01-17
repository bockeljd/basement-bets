# Environment Topology

Basement Bets uses a three-tier environment approach to ensure production stability and enable safe previews of new features.

## 1. LOCAL
- **Target**: `localhost:3000` (Frontend), `localhost:8000` (Backend).
- **Supabase Target**: Supabase Local (via CLI) or the **STAGING** Supabase project.
- **Rules**: Can be used for uncommitted, experimental work.

## 2. PREVIEW (Staging)
- **Target**: Vercel Preview URLs (e.g., `bet-tracker-git-feature-branch.vercel.app`).
- **Supabase Target**: **STAGING** Supabase project.
- **Rules**:
    - Triggered by pushing any branch other than `main`.
    - MUST use STAGING credentials.
    - NEVER touches production data.

## 3. PROD (Production)
- **Target**: `basement-bets.vercel.app` (or custom domain).
- **Supabase Target**: **PROD** Supabase project.
- **Rules**:
    - Triggered by merging to the `main` branch.
    - Isolated from staging/local data.
    - Access to production secrets (e.g., Real Odds API keys).

---

## Promotion Flow
`Local Development` -> `Feature Branch` -> `Vercel Preview (STAGING DB)` -> `Review` -> `Merge to Main` -> `Vercel Production (PROD DB)`
