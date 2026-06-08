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

export function buildDailyPnlSeries(history: TradeHistory[], days = 30) {
  const byDay = new Map<string, number>();
  const today = new Date();
  for (let i = days - 1; i >= 0; i--) {
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
