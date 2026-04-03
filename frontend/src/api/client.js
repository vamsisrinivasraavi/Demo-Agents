import axios from "axios";

const API_BASE = import.meta.env.VITE_API_URL || "/api";

const api = axios.create({
  baseURL: API_BASE,
  headers: { "Content-Type": "application/json" },
});

// Request interceptor — attach JWT
api.interceptors.request.use((config) => {
  const tokens = JSON.parse(localStorage.getItem("tokens") || "null");
  if (tokens?.access_token) {
    config.headers.Authorization = `Bearer ${tokens.access_token}`;
  }
  return config;
});

// Response interceptor — handle 401 + auto-refresh
api.interceptors.response.use(
  (res) => res,
  async (error) => {
    const original = error.config;
    if (error.response?.status === 401 && !original._retry) {
      original._retry = true;
      const tokens = JSON.parse(localStorage.getItem("tokens") || "null");
      if (tokens?.refresh_token) {
        try {
          const { data } = await axios.post(`${API_BASE}/auth/refresh`, {
            refresh_token: tokens.refresh_token,
          });
          localStorage.setItem("tokens", JSON.stringify(data));
          original.headers.Authorization = `Bearer ${data.access_token}`;
          return api(original);
        } catch {
          localStorage.removeItem("tokens");
          localStorage.removeItem("user");
          window.location.href = "/login";
        }
      }
    }
    return Promise.reject(error);
  }
);

// ── Auth ──
export const authApi = {
  register: (data) => api.post("/auth/register", data),
  login: (data) => api.post("/auth/login", data),
  refresh: (data) => api.post("/auth/refresh", data),
  me: () => api.get("/auth/me"),
};

// ── Admin: Ingestion ──
export const ingestionApi = {
  test: (data) => api.post("/admin/ingestion/test-connection", data),
  create: (data) => api.post("/admin/ingestion", data),
  list: (page = 1) => api.get(`/admin/ingestion?page=${page}`),
  get: (id) => api.get(`/admin/ingestion/${id}`),
  delete: (id) => api.delete(`/admin/ingestion/${id}`),
};

// ── Admin: Workflows ──
export const workflowApi = {
  create: (data) => api.post("/admin/workflows", data),
  listAdmin: (page = 1) => api.get(`/admin/workflows?page=${page}`),
  get: (id) => api.get(`/admin/workflows/${id}`),
  update: (id, data) => api.put(`/admin/workflows/${id}`, data),
  delete: (id) => api.delete(`/admin/workflows/${id}`),
  listActive: (page = 1) => api.get(`/user/workflows?page=${page}`),
};

// ── User: Chat ──
export const chatApi = {
  send: (workflowId, data) =>
    api.post(`/user/workflows/${workflowId}/chat`, data),
  listSessions: (params = {}) => {
    const qs = new URLSearchParams(params).toString();
    return api.get(`/user/sessions${qs ? "?" + qs : ""}`);
  },
  getSession: (id) => api.get(`/user/sessions/${id}`),
};

export default api;