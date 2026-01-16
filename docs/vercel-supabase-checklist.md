# Vercel + Supabase Configuration Checklist

Follow these steps to ensure the production environment is secure and correctly integrated.

## Phase 1: Supabase Setup
- [ ] **Create Project**: Initialize a new Supabase project.
- [ ] **Run Baseline Migration**: Execute the SQL from `docs/schema-v1.md` (or the generated migration file) in the SQL Editor.
- [ ] **Enable RLS**: Confirm RLS is enabled on `bets`, `evidence_items`, and `profiles`.
- [ ] **Auth Settings**: Disable public signups if the MVP is invite-only.

## Phase 2: Vercel Integration
- [ ] **Supabase Marketplace Integration**: Use the Vercel-Supabase integration to automatically sync:
    - `POSTGRES_URL`
    - `NEXT_PUBLIC_SUPABASE_URL`
    - `NEXT_PUBLIC_SUPABASE_ANON_KEY`
- [ ] **Manual Secrets**: Add the following in Project Settings > Environment Variables:
    - `SUPABASE_SERVICE_ROLE_KEY`
    - `ODDS_API_KEY`
    - `OPENAI_API_KEY`
    - `BASEMENT_PASSWORD`
- [ ] **Framework Selection**: Ensure Vercel detects "Next.js" correctly.

## Phase 3: Smoke Tests
- [ ] **Health API**: Visit `[YOUR_URL]/api/health` and verify `database_url_present: true`.
- [ ] **Auth Logic**: Verify entering the correct `BASEMENT_PASSWORD` in the frontend (if using password gate) allows API access.
- [ ] **Ingestion**: Upload a test bet slip via DraftKings copy-paste and verify it appears in the Dashboard and links to an `evidence_item`.
