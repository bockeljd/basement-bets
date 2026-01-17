# Auth and Access Strategy (Supabase + Next.js)

This document outlines how we secure the "Basement Bets" application using Supabase Auth and Row Level Security (RLS).

## 1. Authentication Flow

### Client-Side (Next.js)
- **Login/Logout**: Handled via `@supabase/auth-helpers-nextjs` or `@supabase/supabase-js`.
- **Auth State**: Persisted in cookies and accessible via `useSupabaseClient()` or `useSession()`.
- **UI Protection**: High-level routes are protected using middleware or component-level session checks.

### Server-Side (API Routes / SSR)
- **Session Retrieval**: Auth state is extracted from cookies using `createServerComponentClient` or `createRouteHandlerClient`.
- **Header Injection**: For external APIs (Python/FastAPI), the authenticated session token or a verified `user_id` is passed as a header.

## 2. RLS-Safe Access Patterns

### Public/Shared Data
- **Odds Snapshots**: Read-only access for all authenticated users. No write access except via Service Role (ingestion jobs).

### User-Owned Data (Multi-Tenant)
> [!IMPORTANT]
> All user-specific tables (`profiles`, `bankroll_accounts`, `evidence_items`, `bets`) must have a `user_id` column.

- **SELECT/INSERT/UPDATE/DELETE**: Policies enforce `auth.uid() = user_id`.
- **Client Access**: The web frontend uses the `anon` key (Client session) to interact directly with Supabase. RLS ensures users only see their own accounts and bets.

### Elevated Access (System Jobs)
- **Service Role Key**: Used only by server-side ingestion scripts (e.g., fetching odds, grading bets).
- **Restriction**: The Service Role Key must **never** be sent to the client.

## 3. Account Concept (Multiple Bankrolls)

Users can group their bets into "Bankroll Accounts".
- **Default Account**: Every user starts with a 'Main' account created upon signup via a Postgres trigger.
- **Switching**: The UI allows users to select which account they are viewing/logging bets for.
- **Constraints**: RLS policies for `bets` and `evidence_items` will automatically filter based on the `user_id`, regardless of the `account_id` selected.

## 4. Acceptance Criteria (Manual Smoke Tests)

1. **Isolation**: Log in as User A. Create a bet. Log in as User B. Verify User B **cannot** see User A's bet.
2. **Account Switching**: Create two bankrolls ('Personal', 'Testing'). Add a bet to 'Testing'. Switch to 'Personal' and verify the 'Testing' bet is not in the list.
3. **Secret Leakage**: Inspect network requests for the frontend. Verify the `SUPABASE_SERVICE_ROLE_KEY` is nowhere in sight.
