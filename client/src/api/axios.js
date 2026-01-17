import axios from 'axios';
import { config } from '../config';

const api = axios.create({
    baseURL: config.API_URL
});

// Request Interceptor: Inject Token Dynamically
api.interceptors.request.use(
    (config) => {
        const password = localStorage.getItem('basement_password');
        if (password) {
            config.headers['X-BASEMENT-KEY'] = password;
        }
        return config;
    },
    (error) => Promise.reject(error)
);

// Response Interceptor
api.interceptors.response.use(
    response => response,
    error => Promise.reject(error)
);

export default api;
