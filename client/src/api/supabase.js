import { createClient } from '@supabase/supabase-js'
import { config } from '../config'

const supabaseUrl = config.SUPABASE_URL
const supabaseAnonKey = config.SUPABASE_ANON_KEY

if (!supabaseUrl || !supabaseAnonKey) {
    console.warn('Supabase credentials missing. Auth will be disabled.')
}

export const supabase = createClient(
    supabaseUrl || 'https://placeholder.supabase.co',
    supabaseAnonKey || 'placeholder'
)
