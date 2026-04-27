// src/api/client.js
// Base Axios instance — reads API URL from environment variable
// Set VITE_API_URL in frontend/.env

import axios from "axios";

const client = axios.create({
  baseURL: import.meta.env.VITE_API_URL || "http://localhost:8080",
  timeout: 15000,
  headers: { "Content-Type": "application/json" },
});

// Response interceptor — unwrap data, normalize errors
client.interceptors.response.use(
  (res) => res.data,
  (err) => {
    const message =
      err.response?.data?.detail ||
      err.response?.data?.message ||
      err.message ||
      "Unknown error";
    return Promise.reject(new Error(message));
  }
);

export default client;
