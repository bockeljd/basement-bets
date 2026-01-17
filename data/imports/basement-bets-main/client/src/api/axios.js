import axios from 'axios';
import { config } from '../config';

const password = localStorage.getItem('basement_password');

const api = axios.create({
    baseURL: config.API_URL,
    headers: {
        'X-BASEMENT-KEY': password
    }
});

// Add an interceptor to catch 403 (Wrong Password)
api.interceptors.response.use(
    response => response,
    error => {
        if (error.response && error.response.status === 403) {
            const newPass = prompt("Enter Basement Password:");
            if (newPass) {
                localStorage.setItem('basement_password', newPass);
                window.location.reload();
            }
        }
        return Promise.reject(error);
    }
);

export default api;
