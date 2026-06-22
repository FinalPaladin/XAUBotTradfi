import axios, { type AxiosError, type InternalAxiosRequestConfig } from "axios";
import type {
  AdminUserCreate,
  AdminUserUpdate,
  BotConfig,
  BotConfigUpdate,
  BotStatusResponse,
  ChangePasswordRequest,
  ExchangeConfig,
  HistoryQuery,
  LoginRequest,
  MessageResponse,
  SystemLog,
  TokenResponse,
  TradeHistory,
  TradeHistoryPage,
  User,
} from "./types";
import { generateSecureKeyAsync, warmSecureKey } from "./secureKey";
import { getToken, logout } from "./auth";

const API_BASE = import.meta.env.VITE_API_URL ?? "";

export const http = axios.create({
  baseURL: API_BASE,
  headers: { "Content-Type": "application/json" },
});

http.interceptors.request.use(async (config: InternalAxiosRequestConfig) => {
  const secureKey = await generateSecureKeyAsync();
  config.headers.set("X-Secure-Key", secureKey);
  const token = getToken();
  if (token) {
    config.headers.set("Authorization", `Bearer ${token}`);
  }
  return config;
});

http.interceptors.response.use(
  (response) => response,
  (error: AxiosError<{ detail?: string }>) => {
    if (error.response?.status === 401) {
      const url = error.config?.url ?? "";
      if (!url.includes("/api/auth/login")) {
        logout();
        if (window.location.pathname !== "/login") {
          window.location.href = "/login";
        }
      }
    }
    const data = error.response?.data as { detail?: unknown } | string | undefined;
    let message = error.message;
    if (data && typeof data === "object" && "detail" in data) {
      const detail = data.detail;
      if (typeof detail === "string") {
        message = detail;
      } else if (Array.isArray(detail)) {
        message = detail.map((d) => (typeof d === "object" && d && "msg" in d ? String(d.msg) : String(d))).join(", ");
      }
    } else if (typeof data === "string") {
      message = data;
    }
    return Promise.reject(new Error(message));
  },
);

void warmSecureKey();

function normalizeHistoryPage(
  raw: TradeHistoryPage | TradeHistory[],
  params: HistoryQuery,
): TradeHistoryPage {
  if (Array.isArray(raw)) {
    const totalPnl = raw.reduce((sum, row) => sum + row.profit_loss, 0);
    return {
      items: raw,
      total: raw.length,
      page: params.page ?? 1,
      page_size: params.page_size ?? raw.length,
      total_pages: raw.length > 0 ? 1 : 0,
      total_pnl: totalPnl,
    };
  }
  return {
    items: raw.items ?? [],
    total: raw.total ?? 0,
    page: raw.page ?? 1,
    page_size: raw.page_size ?? params.page_size ?? 20,
    total_pages: raw.total_pages ?? 0,
    total_pnl: raw.total_pnl ?? 0,
  };
}

export const api = {
  login: (payload: LoginRequest) =>
    http.post<TokenResponse>("/api/auth/login", payload).then((r) => r.data),

  getMe: () => http.get<User>("/api/auth/me").then((r) => r.data),

  changePassword: (payload: ChangePasswordRequest) =>
    http
      .post<MessageResponse>("/api/auth/change-password", payload)
      .then((r) => r.data),

  listUsers: () => http.get<User[]>("/api/admin/users").then((r) => r.data),

  createUser: (payload: AdminUserCreate) =>
    http.post<User>("/api/admin/users", payload).then((r) => r.data),

  updateUser: (id: number, payload: AdminUserUpdate) =>
    http.put<User>(`/api/admin/users/${id}`, payload).then((r) => r.data),

  getStatus: () =>
    http.get<BotStatusResponse>("/api/bot/status").then((r) => r.data),

  getHistory: async (params: HistoryQuery = {}) => {
    const sp = new URLSearchParams();
    if (params.days != null) sp.set("days", String(params.days));
    if (params.since) sp.set("since", params.since);
    if (params.side) sp.set("side", params.side);
    if (params.pnl && params.pnl !== "ALL") sp.set("pnl", params.pnl);
    if (params.q) sp.set("q", params.q);
    if (params.page != null) sp.set("page", String(params.page));
    if (params.page_size != null) sp.set("page_size", String(params.page_size));
    const qs = sp.toString();
    const raw = await http
      .get<TradeHistoryPage | TradeHistory[]>(
        `/api/bot/history${qs ? `?${qs}` : ""}`,
      )
      .then((r) => r.data);
    return normalizeHistoryPage(raw, params);
  },

  getLogs: (level?: string) => {
    const q = level ? `?level=${level}` : "";
    return http.get<SystemLog[]>(`/api/bot/logs${q}`).then((r) => r.data);
  },

  getExchanges: () =>
    http.get<ExchangeConfig[]>("/api/bot/exchanges").then((r) => r.data),

  checkExchanges: () =>
    http.get<ExchangeConfig[]>("/api/bot/exchanges/check").then((r) => r.data),

  getConfigs: () =>
    http.get<BotConfig[]>("/api/bot/config").then((r) => r.data),

  updateConfig: (payload: BotConfigUpdate) =>
    http.post<BotConfig>("/api/bot/config", payload).then((r) => r.data),

  startBot: (id: number) =>
    http.post<BotConfig>(`/api/bot/${id}/start`).then((r) => r.data),

  stopBot: (id: number) =>
    http.post<BotConfig>(`/api/bot/${id}/stop`).then((r) => r.data),

  closePosition: (positionId: number) =>
    http
      .post<MessageResponse>(`/api/bot/positions/${positionId}/close`)
      .then((r) => r.data),

  closeAllPositions: () =>
    http
      .post<MessageResponse>("/api/bot/positions/close-all")
      .then((r) => r.data),

  resyncHistoryPnl: () =>
    http
      .post<MessageResponse>("/api/bot/history/resync-pnl")
      .then((r) => r.data),
};
