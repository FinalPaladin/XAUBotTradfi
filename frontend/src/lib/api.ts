import type {
  BotConfig,
  BotConfigUpdate,
  BotStatusResponse,
  ExchangeConfig,
  SystemLog,
  TradeHistory,
} from "./types";

const API_BASE = import.meta.env.VITE_API_URL ?? "";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    headers: { "Content-Type": "application/json", ...init?.headers },
    ...init,
  });
  if (!res.ok) {
    const body = await res.text();
    throw new Error(body || res.statusText);
  }
  return res.json() as Promise<T>;
}

export const api = {
  getStatus: () => request<BotStatusResponse>("/api/bot/status"),
  getHistory: (limit = 500) =>
    request<TradeHistory[]>(`/api/bot/history?limit=${limit}`),
  getLogs: (level?: string) => {
    const q = level ? `?level=${level}` : "";
    return request<SystemLog[]>(`/api/bot/logs${q}`);
  },
  getExchanges: () => request<ExchangeConfig[]>("/api/bot/exchanges"),
  getConfigs: () => request<BotConfig[]>("/api/bot/config"),
  updateConfig: (payload: BotConfigUpdate) =>
    request<BotConfig>("/api/bot/config", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  startBot: (id: number) =>
    request<BotConfig>(`/api/bot/${id}/start`, { method: "POST" }),
  stopBot: (id: number) =>
    request<BotConfig>(`/api/bot/${id}/stop`, { method: "POST" }),
};
