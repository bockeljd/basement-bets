import axios from 'axios';
import { config } from '../config';
import { loadCache, saveCache } from '../utils/httpCache';

const api = axios.create({
    baseURL: config.API_URL
});

// Only cache a few read-heavy endpoints.
const CACHEABLE_GETS = new Set([
    '/api/board',
    '/api/ncaam/top-picks',
    '/api/ncaam/history'
]);

// Request Interceptor: Inject Token Dynamically
api.interceptors.request.use(
    (cfg) => {
        const password = localStorage.getItem('basement_password');
        if (password) {
            cfg.headers['X-BASEMENT-KEY'] = password;
        }

        // ETag revalidation for a small set of heavy GET endpoints.
        try {
            const method = (cfg.method || 'get').toLowerCase();
            const url = cfg.url;
            if (method === 'get' && url && CACHEABLE_GETS.has(url)) {
                const cached = loadCache(url, cfg.params);
                if (cached?.etag) {
                    cfg.headers['If-None-Match'] = cached.etag;
                }
            }
        } catch {
            // ignore
        }

        return cfg;
    },
    (error) => Promise.reject(error)
);

// Response Interceptor
api.interceptors.response.use(
    (response) => {
        try {
            const method = (response?.config?.method || 'get').toLowerCase();
            const url = response?.config?.url;
            if (method === 'get' && url && CACHEABLE_GETS.has(url) && response?.status === 200 && response?.data != null) {
                const etag = response?.headers?.etag || null;
                const params = response?.config?.params;
                saveCache(url, params, response.data, etag);
                if (url === '/api/ncaam/top-picks' && params && Object.prototype.hasOwnProperty.call(params, 'refresh')) {
                    const { refresh: _omitRefresh, ...baseParams } = params;
                    saveCache(url, baseParams, response.data, etag);
                }
            }
        } catch {
            // ignore
        }
        return response;
    },
    (error) => {
        // Global auth UX: if we get a 403 anywhere, prompt once for Basement password.
        // Individual pages also handle this, but many components call APIs directly.
        try {
            const status = error?.response?.status;
            if (status === 403 && typeof window !== 'undefined') {
                const k = 'basement_password_prompted';
                // Avoid prompt loops in case the password is wrong.
                const already = (() => {
                    try { return sessionStorage.getItem(k) === '1'; } catch { return false; }
                })();

                if (!already) {
                    try { sessionStorage.setItem(k, '1'); } catch { }
                    const pass = window.prompt('Authentication failed. Please enter the Basement Password:');
                    if (pass) {
                        try { localStorage.setItem('basement_password', pass); } catch { }
                        window.location.reload();
                        // Return a never-resolving promise: the page is reloading.
                        return new Promise(() => { });
                    }
                }
            }
        } catch {
            // ignore
        }

        // If server returns 304, Axios may treat it as error depending on config.
        // Try to serve cached payload.
        try {
            const status = error?.response?.status;
            const cfg = error?.config;
            const method = (cfg?.method || 'get').toLowerCase();
            const url = cfg?.url;
            if (status === 304 && method === 'get' && url && CACHEABLE_GETS.has(url)) {
                const cached = loadCache(url, cfg.params);
                if (cached?.payload != null) {
                    return Promise.resolve({
                        ...error.response,
                        status: 200,
                        data: cached.payload,
                        _fromCache: true,
                    });
                }
            }
        } catch {
            // ignore
        }
        return Promise.reject(error);
    }
);

export default api;
