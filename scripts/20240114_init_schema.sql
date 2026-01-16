-- Baseline Migration for Basement Bets
-- Date: 2024-01-14

-- 1. Tables
CREATE TABLE IF NOT EXISTS public.profiles (
    id UUID PRIMARY KEY REFERENCES auth.users ON DELETE CASCADE,
    email TEXT,
    is_premium BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    last_ingested_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS public.bankroll_accounts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES auth.users ON DELETE CASCADE,
    name TEXT NOT NULL,
    provider_sync TEXT,
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(user_id, name)
);

CREATE TABLE IF NOT EXISTS public.evidence_items (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES auth.users ON DELETE CASCADE,
    account_id UUID REFERENCES public.bankroll_accounts ON DELETE SET NULL,
    raw_content TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    source TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(user_id, content_hash)
);

CREATE TABLE IF NOT EXISTS public.bets (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES auth.users ON DELETE CASCADE,
    account_id UUID NOT NULL REFERENCES public.bankroll_accounts ON DELETE CASCADE,
    evidence_id UUID REFERENCES public.evidence_items ON DELETE SET NULL,
    placed_at TIMESTAMPTZ NOT NULL,
    description TEXT,
    selection TEXT,
    stake NUMERIC NOT NULL,
    odds_dec NUMERIC NOT NULL,
    payout NUMERIC,
    status TEXT DEFAULT 'Pending' CHECK (status IN ('Pending', 'Won', 'Lost', 'Pushed')),
    raw_slip_hash TEXT NOT NULL,
    dedupe_fingerprint TEXT NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(user_id, raw_slip_hash),
    UNIQUE(user_id, account_id, description, placed_at, stake, selection)
);

CREATE TABLE IF NOT EXISTS public.odds_snapshots (
    id BIGSERIAL PRIMARY KEY,
    event_id TEXT NOT NULL,
    sport_key TEXT NOT NULL,
    provider TEXT,
    bookmaker TEXT,
    market TEXT,
    selection TEXT,
    line NUMERIC,
    price NUMERIC,
    timestamp TIMESTAMPTZ DEFAULT NOW(),
    snapshot_bucket TIMESTAMPTZ NOT NULL,
    UNIQUE(event_id, market, bookmaker, selection, snapshot_bucket)
);

CREATE TABLE IF NOT EXISTS public.ingestion_logs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID REFERENCES auth.users ON DELETE SET NULL,
    job_name TEXT NOT NULL,
    status TEXT,
    summary JSONB,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- 2. RLS Setup
ALTER TABLE public.profiles ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.bankroll_accounts ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.evidence_items ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.bets ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.odds_snapshots ENABLE ROW LEVEL SECURITY;

-- 3. Policies
CREATE POLICY "Users can view own profile" ON public.profiles FOR SELECT USING (auth.uid() = id);

CREATE POLICY "Users can CRUD own bankrolls" ON public.bankroll_accounts ALL USING (auth.uid() = user_id);

CREATE POLICY "Users can CRUD own evidence" ON public.evidence_items ALL USING (auth.uid() = user_id);

CREATE POLICY "Users can CRUD own bets" ON public.bets ALL USING (auth.uid() = user_id);

CREATE POLICY "Public Read Odds" ON public.odds_snapshots FOR SELECT USING (true);

-- 4. Triggers
-- Automatically create profile and 'Main' account on signup
CREATE OR REPLACE FUNCTION public.handle_new_user()
RETURNS trigger AS $$
BEGIN
  INSERT INTO public.profiles (id, email)
  VALUES (new.id, new.email);
  
  INSERT INTO public.bankroll_accounts (user_id, name)
  VALUES (new.id, 'Main');
  
  RETURN new;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

CREATE TRIGGER on_auth_user_created
  AFTER INSERT ON auth.users
  FOR EACH ROW EXECUTE PROCEDURE public.handle_new_user();

-- 5. Indexes
CREATE INDEX IF NOT EXISTS idx_bets_user_date ON public.bets (user_id, placed_at DESC);
CREATE INDEX IF NOT EXISTS idx_odds_event_time ON public.odds_snapshots (event_id, timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_evidence_hash ON public.evidence_items (user_id, content_hash);
