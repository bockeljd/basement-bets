import axios from 'axios';
import { config } from '../config';

const password = localStorage.getItem('basement_password');

const api = axios.create({
    baseURL: config.API_URL,
    headers: {
        'X-BASEMENT-KEY': password
    }
});

// Interceptor removed. App.jsx handles 403.
api.interceptors.response.use(
    response => response,
    error => Promise.reject(error)
);

export default api;
