/**
 * Centralized Environment Configuration
 */

const env = import.meta.env;

export const config = {
    APP_ENV: env.VITE_PUBLIC_APP_ENV || 'local',
    SUPABASE_URL: env.VITE_SUPABASE_URL || env.VITE_PUBLIC_SUPABASE_URL,
    SUPABASE_ANON_KEY: env.VITE_SUPABASE_ANON_KEY || env.VITE_PUBLIC_SUPABASE_ANON_KEY,
    API_URL: env.VITE_API_URL || '',

    // Derived properties
    isProd: (env.VITE_PUBLIC_APP_ENV || 'local') === 'prod',
    isLocal: (env.VITE_PUBLIC_APP_ENV || 'local') === 'local',
    isPreview: (env.VITE_PUBLIC_APP_ENV || 'local') === 'preview',
};

// Validation
if (!config.SUPABASE_URL || !config.SUPABASE_ANON_KEY) {
    console.error("[CRITICAL] Supabase credentials missing from Environment.");
}

if (!config.isProd) {
    console.info(`[ENV] Running in ${config.APP_ENV} mode.`);
}
