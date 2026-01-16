# Environment Contract: Basement Bets

This document defines the interface between the application and its deployment environments (Local, Vercel, Supabase).

## 1. Secrets Handling Policy
> [!CAUTION]
> - **Service Role Keys** (`SUPABASE_SERVICE_ROLE_KEY`) and **API Keys** (`OPENAI_API_KEY`, `ODDS_API_KEY`) must **NEVER** be prefixed with `NEXT_PUBLIC_`.
> - **Client Exposure**: Only variables prefixed with `NEXT_PUBLIC_` are bundled into the browser.
> - **Server Storage**: In Vercel, sensitive keys must be stored as "Encrypted Environment Variables".

## 2. Environment Variables Registry

### Supabase (Auth & DB)
| Variable | Type | Exposure | Description |
| :--- | :--- | :--- | :--- |
| `NEXT_PUBLIC_SUPABASE_URL` | URL | Client/Server | The URL of your Supabase project. |
| `NEXT_PUBLIC_SUPABASE_ANON_KEY` | Key | Client/Server | Public API key (safe for browser). |
| `SUPABASE_SERVICE_ROLE_KEY` | Key | **Server Only** | Admin key bypasses RLS. |

### Data Providers & Models
| Variable | Type | Exposure | Description |
| :--- | :--- | :--- | :--- |
| `ODDS_API_KEY` | Key | **Server Only** | API Key for The Odds API. |
| `OPENAI_API_KEY` | Key | **Server Only** | Used for LLM-based parsing and analysis. |
| `BASEMENT_PASSWORD` | Text | **Server Only** | Simple gate for the `/api` routes (MVP). |

### Database Connections (Legacy/Background)
| Variable | Type | Exposure | Description |
| :--- | :--- | :--- | :--- |
| `POSTGRES_URL` | Connection | **Server Only** | Direct Postgres connection string (Neon/Supabase). |

## 3. Local Development Setup

1. Copy `.env.template` to `.env.local`:
   ```bash
   cp .env.template .env.local
   ```
2. Populate `NEXT_PUBLIC_SUPABASE_URL` and `NEXT_PUBLIC_SUPABASE_ANON_KEY`.
3. Set `BASEMENT_PASSWORD` to a dev secret.
4. Run the stack:
   ```bash
   npm run dev
   ```

## 4. Vercel Deployment Checklist

- [ ] Connect Supabase Integration (automatically sets `POSTGRES_URL`).
- [ ] Manually add `ODDS_API_KEY` and `OPENAI_API_KEY`.
- [ ] Ensure `NEXT_PUBLIC_` prefix is used correctly for frontend keys.
- [ ] Set `BASEMENT_PASSWORD` for API protection.
