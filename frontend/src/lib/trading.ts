import type { OrderSide, TradeHistory, TradePosition } from "./types";

export function positionNotional(volume: number, price: number) {
  return volume * price * 100;
}

export function unrealizedPnl(
  side: OrderSide,
  entry: number,
  market: number | null | undefined,
  volume: number,
): number | null {
  if (market == null) return null;
  const diff = side === "BUY" ? market - entry : entry - market;
  return diff * volume * 100;
}

export function marketPrice(
  position: TradePosition,
  ticks?: Record<string, number | null>,
  live?: Record<string, { price_current: number; profit: number } | undefined>,
): number | null {
  const fromMt5 = live?.[position.ticket_id]?.price_current;
  if (fromMt5 != null) return fromMt5;

  const tick = ticks?.[position.symbol];
  if (tick != null) return tick;

  return null;
}

export function unrealizedPnlFromLive(
  position: TradePosition,
  live?: Record<
    string,
    { price_current: number; profit: number; swap?: number } | undefined
  >,
): number | null {
  const p = live?.[position.ticket_id];
  if (p != null) return p.profit + (p.swap ?? 0);
  return null;
}

export type DashboardDaysFilter = 0 | 7 | 30 | 90;

export function startOfTodayLocalIso() {
  const start = new Date();
  start.setHours(0, 0, 0, 0);
  return start.toISOString();
}

export function dashboardPeriodLabel(days: DashboardDaysFilter) {
  if (days === 0) return "hôm nay";
  return `${days} ngày gần nhất`;
}

export function effectiveDashboardDays(days: DashboardDaysFilter) {
  return days === 0 ? 1 : days;
}

export function buildDailyPnlSeries(
  history: TradeHistory[],
  days: DashboardDaysFilter | number = 30,
) {
  const span = typeof days === "number" && days === 0 ? 1 : days;
  const byDay = new Map<string, number>();
  const today = new Date();
  for (let i = span - 1; i >= 0; i--) {
    const d = new Date(today);
    d.setDate(today.getDate() - i);
    byDay.set(d.toISOString().slice(0, 10), 0);
  }
  for (const row of history) {
    const key = row.closed_at.slice(0, 10);
    if (byDay.has(key)) {
      byDay.set(key, (byDay.get(key) ?? 0) + row.profit_loss);
    }
  }
  let cumulative = 0;
  return Array.from(byDay.entries()).map(([date, pnl]) => {
    cumulative += pnl;
    return {
      date: date.slice(5),
      pnl: Math.round(pnl * 100) / 100,
      cumulative: Math.round(cumulative * 100) / 100,
    };
  });
}

export function todayPnl(history: TradeHistory[]) {
  const today = new Date().toISOString().slice(0, 10);
  return history
    .filter((h) => h.closed_at.startsWith(today))
    .reduce((s, h) => s + h.profit_loss, 0);
}

export interface DailyMetricsRow {
  date: string;
  totalTrades: number;
  wins: number;
  losses: number;
  winRate: number;
  pnl: number;
  avgPnl: number;
  avgHoldMinutes: number;
  profitLossRatio: number | null;
  roe: number | null;
}

function holdMinutes(row: TradeHistory) {
  const opened = new Date(row.opened_at).getTime();
  const closed = new Date(row.closed_at).getTime();
  return Math.max(0, (closed - opened) / 60_000);
}

export function buildDailyMetricsRows(
  history: TradeHistory[],
  days: DashboardDaysFilter,
  baseEquityUsd?: number,
): DailyMetricsRow[] {
  const span = effectiveDashboardDays(days);
  const today = new Date();
  const dayKeys: string[] = [];
  for (let i = span - 1; i >= 0; i--) {
    const d = new Date(today);
    d.setDate(today.getDate() - i);
    dayKeys.push(d.toISOString().slice(0, 10));
  }

  const byDay = new Map<string, TradeHistory[]>();
  for (const key of dayKeys) byDay.set(key, []);
  for (const row of history) {
    const key = row.closed_at.slice(0, 10);
    const bucket = byDay.get(key);
    if (bucket) bucket.push(row);
  }

  return dayKeys
    .map((key) => {
      const trades = byDay.get(key) ?? [];
      const wins = trades.filter((t) => t.profit_loss > 0);
      const losses = trades.filter((t) => t.profit_loss < 0);
      const totalTrades = trades.length;
      const pnl = trades.reduce((s, t) => s + t.profit_loss, 0);
      const avgPnl = totalTrades > 0 ? pnl / totalTrades : 0;
      const winRate = totalTrades > 0 ? (wins.length / totalTrades) * 100 : 0;
      const avgHoldMinutes =
        totalTrades > 0
          ? trades.reduce((s, t) => s + holdMinutes(t), 0) / totalTrades
          : 0;
      const avgWin =
        wins.length > 0
          ? wins.reduce((s, t) => s + t.profit_loss, 0) / wins.length
          : 0;
      const avgLoss =
        losses.length > 0
          ? Math.abs(
              losses.reduce((s, t) => s + t.profit_loss, 0) / losses.length,
            )
          : 0;
      const profitLossRatio = avgLoss > 0 ? avgWin / avgLoss : null;
      const roe =
        baseEquityUsd && baseEquityUsd > 0
          ? (pnl / baseEquityUsd) * 100
          : null;

      return {
        date: key.slice(5),
        totalTrades,
        wins: wins.length,
        losses: losses.length,
        winRate: Math.round(winRate * 100) / 100,
        pnl: Math.round(pnl * 100) / 100,
        avgPnl: Math.round(avgPnl * 100) / 100,
        avgHoldMinutes: Math.round(avgHoldMinutes * 100) / 100,
        profitLossRatio:
          profitLossRatio != null
            ? Math.round(profitLossRatio * 100) / 100
            : null,
        roe: roe != null ? Math.round(roe * 100) / 100 : null,
      };
    })
    .reverse();
}
