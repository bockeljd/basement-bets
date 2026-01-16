-- Provider Ingestion Runs
CREATE TABLE IF NOT EXISTS provider_ingestion_runs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    provider TEXT NOT NULL,
    run_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    status TEXT NOT NULL,
    rows_processed INTEGER,
    error_log JSONB
);

-- BartTorvik Raw Artifacts
CREATE TABLE IF NOT EXISTS bt_raw_artifacts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source TEXT DEFAULT 'barttorvik',
    snapshot_date DATE NOT NULL,
    fetched_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    storage_path TEXT NOT NULL,
    content_hash TEXT,
    status TEXT NOT NULL
);

-- BartTorvik Daily Metrics
CREATE TABLE IF NOT EXISTS bt_team_metrics_daily (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    team_id TEXT NOT NULL,
    date DATE NOT NULL,
    season INTEGER,
    adj_oe FLOAT,
    adj_de FLOAT,
    barthag FLOAT,
    tempo FLOAT,
    rank INTEGER,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(team_id, date)
);

-- Model Ops: Versioning
CREATE TABLE IF NOT EXISTS model_versions (
    version_id TEXT PRIMARY KEY,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    status TEXT NOT NULL, -- 'active', 'experimental', 'retired'
    config_json JSONB,
    description TEXT
);

-- Model Ops: Daily Health
CREATE TABLE IF NOT EXISTS model_health_daily (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    model_version TEXT REFERENCES model_versions(version_id),
    date DATE NOT NULL,
    sample_size INTEGER,
    n_actionable INTEGER,
    brier_score FLOAT,
    log_loss FLOAT,
    roi_actionable FLOAT,
    ece FLOAT,
    is_degrading_7d BOOLEAN,
    penalty_factor FLOAT,
    notes TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Ingestion Quarantine
CREATE TABLE IF NOT EXISTS bt_ingestion_quarantine (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    run_id UUID REFERENCES provider_ingestion_runs(id),
    raw_row JSONB,
    reason TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Migration for Existing Tables (safe fallback if column missing)
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='model_predictions' AND column_name='data_snapshot_date') THEN
        ALTER TABLE model_predictions ADD COLUMN data_snapshot_date DATE;
    END IF;
    
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='model_predictions' AND column_name='model_version_id') THEN
        ALTER TABLE model_predictions ADD COLUMN model_version_id TEXT REFERENCES model_versions(version_id);
    END IF;
    
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='model_predictions' AND column_name='data_snapshot_id') THEN
        ALTER TABLE model_predictions ADD COLUMN data_snapshot_id UUID REFERENCES bt_raw_artifacts(id);
    END IF;
END $$;
