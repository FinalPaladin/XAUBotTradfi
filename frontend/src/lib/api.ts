import type {
  BotConfig,
  BotConfigUpdate,
  BotStatusResponse,
  ExchangeConfig,
  HistoryQuery,
  MessageResponse,
  SystemLog,
  TradeHistory,
  TradeHistoryPage,
} from "./types";

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
    const raw = await request<TradeHistoryPage | TradeHistory[]>(
      `/api/bot/history${qs ? `?${qs}` : ""}`,
    );
    return normalizeHistoryPage(raw, params);
  },
  getLogs: (level?: string) => {
    const q = level ? `?level=${level}` : "";
    return request<SystemLog[]>(`/api/bot/logs${q}`);
  },
  getExchanges: () => request<ExchangeConfig[]>("/api/bot/exchanges"),
  checkExchanges: () =>
    request<ExchangeConfig[]>("/api/bot/exchanges/check"),
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
  closePosition: (positionId: number) =>
    request<MessageResponse>(`/api/bot/positions/${positionId}/close`, {
      method: "POST",
    }),
  closeAllPositions: () =>
    request<MessageResponse>("/api/bot/positions/close-all", {
      method: "POST",
    }),
  resyncHistoryPnl: () =>
    request<MessageResponse>("/api/bot/history/resync-pnl", {
      method: "POST",
    }),
};
