# Vercel Postgres (Neon) Setup Guide

This project is configured to work with **Vercel Postgres** (powered by Neon) out of the box. It prefers **Pooled** connections for runtime (API) and **Direct** connections for migrations.

## Environment Variables

When you link a Vercel Postgres store, Vercel automatically injects the following variables. `src/config.py` resolves them in this priority order:

### Runtime (Pooled)
1.  `DATABASE_URL` (Manual Override or Neon default)
2.  `POSTGRES_URL` (Vercel Standard)
3.  `POSTGRES_PRISMA_URL` (Vercel Pooled)
4.  `POSTGRES_URL_NON_POOLING` (Fallback - **Avoid in Serverless**)

### Migrations (Direct)
1.  `DATABASE_URL_UNPOOLED` (Neon Standard)
2.  `POSTGRES_URL_NON_POOLING` (Vercel Standard)

## Local Development

### Option A: Use Vercel Cloud DB Locally (Easiest)
1.  Link your project: `vercel link`
2.  Pull env vars: `vercel env pull .env.local`
3.  Run the app. It will connect to your Vercel DB.

### Option B: Local Docker Postgres
1.  Run a local Postgres instance (e.g., via Docker).
2.  Set `DATABASE_URL=postgresql://user:pass@localhost:5432/bet_tracker` in `.env`.
3.  Set `BASEMENT_DB_RESET=0` (Safe Mode).

## Safety & Resets

By default, the application **never drops tables**, even if you run `/api/admin/init-db`.
To perform a full destructive reset (wipe all data):
1.  Set `BASEMENT_DB_RESET=1` in your environment variables.
2.  Run `/api/admin/init-db` (or `make init-db`).
3.  **Immediately un-set** the variable after use.

## Troubleshooting

-   **"Missing required environment variables"**: Ensure `DATABASE_URL` or `POSTGRES_URL` is set.
-   **"Connection Limit Exceeded"**: Ensure runtime is using the **Pooled** URL (`POSTGRES_URL` not `_NON_POOLING`).
