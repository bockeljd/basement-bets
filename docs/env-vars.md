# Environment Variables Contract

To ensure security and prevent secret leakage, Basement Bets enforces a strict classification for all environment variables.

## Classification Levels

### 🟢 CLIENT-SAFE (`VITE_PUBLIC_*`)
- **Vite Prefix**: Must start with `VITE_PUBLIC_` to be bundled into the frontend.
- **Security**: Contains NO secrets. Safe for browser exposure.
- **Examples**: `VITE_PUBLIC_SUPABASE_URL`, `VITE_PUBLIC_APP_ENV`.

### 🔴 SERVER-ONLY
- **Prefix**: None.
- **Security**: Contains sensitive secrets. MUST NEVER be imported by client-side code.
- **Examples**: `SUPABASE_SERVICE_ROLE_KEY`, `OPENAI_API_KEY`, `POSTGRES_URL`.

## Required Variables

| Name | Level | Environments | Description |
| :--- | :--- | :--- | :--- |
| `APP_ENV` | 🔴 | ALL | `local`, `preview`, or `prod`. |
| `VITE_PUBLIC_APP_ENV` | 🟢 | ALL | Mirrors `APP_ENV` for the UI. |
| `VITE_PUBLIC_SUPABASE_URL` | 🟢 | ALL | URL for your Supabase project. |
| `VITE_PUBLIC_SUPABASE_ANON_KEY` | 🟢 | ALL | Public anon key for RLS. |
| `POSTGRES_URL` | 🔴 | ALL | Connection string for Postgres. |
| `SUPABASE_SERVICE_ROLE_KEY` | 🔴 | PROD/STAGING | Admin key for bypass operations. |
| `OPENAI_API_KEY` | 🔴 | ALL | For LLM slip parsing. |

## Enforcement
- **Build-time Check**: The build will fail if `APP_ENV` is missing.
- **Runtime Guard**: The backend will crash if `APP_ENV != 'prod'` but `POSTGRES_URL` points to a production database.
- **Access Rule**: The `SUPABASE_SERVICE_ROLE_KEY` is zeroed out in the client bundle.
