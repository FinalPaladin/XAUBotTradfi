export type BotStatus = "RUNNING" | "STOPPED";
export type OrderSide = "BUY" | "SELL";
export type LogLevel = "DEBUG" | "INFO" | "WARNING" | "ERROR";

export interface BotConfig {
  id: number;
  name: string;
  status: BotStatus;
  symbol: string;
  timeframe: string;
  bars_lookback: number;
  risk_per_trade_pct: number;
  max_open_positions: number;
  magic_number: number;
  rsi_swing_lookback: number;
  take_profit_pct: number;
  stop_loss_pct: number;
  trailing_stop_enabled: boolean;
  trailing_stop_pct: number | null;
  donchian_period: number;
  donchian_weight: number;
  supertrend_period: number;
  supertrend_multiplier: number;
  supertrend_weight: number;
  rsi_period: number;
  rsi_overbought: number;
  rsi_oversold: number;
  rsi_weight: number;
  ema_period: number;
  ema_weight: number;
  signal_threshold: number;
  max_layers: number;
  isolated_leverage: number;
  base_equity_usd: number;
  first_layer_notional_usd: number;
  dca_volume_multiplier: number;
  layer_spacing_min: number;
  layer_spacing_max: number;
  basket_tp_min_usd: number;
  basket_tp_max_usd: number;
  single_tp_min_usd: number;
  single_tp_max_usd: number;
  single_tp_distance: number;
  hard_stop_adverse_distance: number;
  max_basket_loss_usd: number;
  max_basket_loss_pct: number;
  counter_trend_max_layers: number;
  atr_stop_multiplier: number;
  basket_time_stop_minutes: number;
  created_at: string;
  updated_at: string;
}

export interface TradePosition {
  id: number;
  bot_id: number;
  ticket_id: string;
  symbol: string;
  side: OrderSide;
  volume: number;
  entry_price: number;
  current_tp: number | null;
  current_sl: number | null;
  highest_price: number | null;
  lowest_price: number | null;
  basket_peak_pnl: number | null;
  layer_index: number;
  basket_anchor_price: number | null;
  opened_at: string;
}

export interface TradeHistory {
  id: number;
  bot_id: number;
  ticket_id: string;
  symbol: string;
  side: OrderSide;
  volume: number;
  entry_price: number;
  exit_price: number;
  profit_loss: number;
  close_reason: string | null;
  opened_at: string;
  closed_at: string;
}

export interface TradeHistoryPage {
  items: TradeHistory[];
  total: number;
  page: number;
  page_size: number;
  total_pages: number;
  total_pnl: number;
}

export type HistoryPnlFilter = "ALL" | "WIN" | "LOSS";

export interface HistoryQuery {
  days?: number;
  since?: string;
  side?: OrderSide;
  pnl?: HistoryPnlFilter;
  q?: string;
  page?: number;
  page_size?: number;
}

export interface BotStatusResponse {
  bots: BotConfig[];
  open_positions: TradePosition[];
  recent_history: TradeHistory[];
  meta: {
    mt5_connected?: boolean;
    mt5_error?: string | null;
    account?: Record<string, unknown> | null;
    symbol_ticks?: Record<string, number | null>;
    position_live?: Record<
      string,
      { price_current: number; profit: number; swap?: number }
    >;
    last_check?: string;
  };
}

export interface SystemLog {
  id: number;
  bot_id: number | null;
  level: LogLevel;
  source: string;
  message: string;
  created_at: string;
}

export interface ExchangeConfig {
  id: string;
  name: string;
  platform: string;
  server: string | null;
  login: string | null;
  connected: boolean;
  error: string | null;
  extra: Record<string, unknown>;
}

export interface MessageResponse {
  message: string;
  detail?: Record<string, unknown> | null;
}

export type BotConfigUpdate = Partial<
  Omit<BotConfig, "id" | "created_at" | "updated_at">
> & { id?: number };
