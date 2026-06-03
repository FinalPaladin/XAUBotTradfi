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
  signal_threshold: number;
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

export interface BotStatusResponse {
  bots: BotConfig[];
  open_positions: TradePosition[];
  recent_history: TradeHistory[];
  meta: {
    mt5_connected?: boolean;
    mt5_error?: string | null;
    account?: Record<string, unknown> | null;
    symbol_ticks?: Record<string, number | null>;
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

export type BotConfigUpdate = Partial<
  Omit<BotConfig, "id" | "created_at" | "updated_at">
> & { id?: number };
