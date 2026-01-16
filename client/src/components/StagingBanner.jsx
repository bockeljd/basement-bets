import React from 'react';
import { config } from '../config';
import { AlertTriangle } from 'lucide-react';

export function StagingBanner() {
    if (config.isProd) return null;

    const envName = config.APP_ENV.toUpperCase();
    const bgColor = config.isLocal ? 'bg-amber-500' : 'bg-blue-600';

    return (
        <div className={`${bgColor} text-white px-4 py-1 text-[10px] font-bold tracking-widest flex items-center justify-center gap-2 sticky top-0 z-[100] shadow-md uppercase`}>
            <AlertTriangle size={12} />
            Environment: {envName} — Using Staging Data
            <AlertTriangle size={12} />
        </div>
    );
}
