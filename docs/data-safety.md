# Data Safety & Environment Isolation

Basement Bets enforces a strict "no production data in staging/local" policy to protect user information and maintain ledger integrity.

## Guardrails

### 1. Connection Guard (Server-side)
The backend `config.py` performs a string check on the `POSTGRES_URL`. 
- **Rule**: If `APP_ENV != 'prod'` and the connection string contains the production Supabase reference (e.g., `prod-db-id`), the application will raise a `RuntimeError` and exit immediately.
- **Why**: Prevents accidental migrations or manual experiments from affecting the live database.

### 2. Visual Staging Banner (Frontend)
- **Rule**: If `VITE_PUBLIC_APP_ENV != 'prod'`, a persistent banner appears at the top or corner of the application.
- **Banner Text**: `ENVIRONMENT: [LOCAL | PREVIEW] - STAGING DATA`
- **Why**: Ensures developers and testers are always aware of which data source they are modifying.

### 3. Service Role Key Protection
- **Rule**: The `SUPABASE_SERVICE_ROLE_KEY` is restricted to server-side code only.
- **Why**: Service role keys bypass RLS. Exposing them to the client is a critical security vulnerability.

---

## Accidental Leakage Checklist
- [ ] No `production` branch in git (use `main`).
- [ ] No hardcoded database credentials in the codebase.
- [ ] No `.env` files committed to the repository.
- [ ] Staging and Production Supabase projects use different DB passwords.
