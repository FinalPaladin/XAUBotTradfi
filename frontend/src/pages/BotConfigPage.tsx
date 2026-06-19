import { useEffect, useState } from "react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { api } from "@/lib/api";
import type { BotConfig, TradingMode } from "@/lib/types";

const TIMEFRAMES = ["M1", "M5", "M15", "M30", "H1", "H4", "D1"] as const;

const TRADING_MODES: {
  value: TradingMode;
  title: string;
  description: string;
}[] = [
  {
    value: "NORMAL",
    title: "Normal",
    description:
      "DCA 4 lớp, spacing 4 giá, chốt ~$1, full stack lỗ 40% balance.",
  },
  {
    value: "SUPER_SAFE",
    title: "Siêu an toàn",
    description:
      "Chỉ vào thuận H1 + score cao, tối đa 2 lớp, chốt nhanh hơn. Dùng ngày news/risk cao.",
  },
];

function sanitizeConfig(config: BotConfig): BotConfig {
  const atr = config.atr_stop_multiplier;
  return {
    ...config,
    atr_stop_multiplier:
      atr > 10 || atr < 0.5 ? 2.0 : atr,
  };
}

function formatSaveError(raw: string): string {
  try {
    const parsed = JSON.parse(raw) as {
      detail?: string | Array<{ loc?: string[]; msg?: string }>;
    };
    if (Array.isArray(parsed.detail)) {
      return parsed.detail
        .map((d) => {
          const field = d.loc?.slice(-1)[0] ?? "field";
          return `${field}: ${d.msg ?? "invalid"}`;
        })
        .join("; ");
    }
    if (typeof parsed.detail === "string") {
      return parsed.detail;
    }
  } catch {
    /* keep raw message */
  }
  return raw;
}

export function BotConfigPage() {
  const [bot, setBot] = useState<BotConfig | null>(null);
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState("");

  useEffect(() => {
    api.getConfigs().then((list) => {
      const config = list[0];
      setBot(config ? sanitizeConfig(config) : null);
    });
  }, []);

  function updateField<K extends keyof BotConfig>(key: K, value: BotConfig[K]) {
    if (!bot) return;
    setBot({ ...bot, [key]: value });
  }

  async function handleSave() {
    if (!bot) return;
    setSaving(true);
    setMessage("");
    try {
      const { id, created_at, updated_at, ...payload } = sanitizeConfig(bot);
      const saved = await api.updateConfig({ ...payload, id });
      setBot(saved);
      setMessage("Đã lưu cấu hình");
    } catch (e) {
      const raw = e instanceof Error ? e.message : "Lỗi lưu";
      setMessage(formatSaveError(raw));
    } finally {
      setSaving(false);
    }
  }

  async function toggleRun() {
    if (!bot) return;
    try {
      const next =
        bot.status === "RUNNING"
          ? await api.stopBot(bot.id)
          : await api.startBot(bot.id);
      setBot(next);
    } catch (e) {
      setMessage(e instanceof Error ? e.message : "Lỗi điều khiển bot");
    }
  }

  if (!bot) {
    return <p className="text-muted-foreground">Chưa có cấu hình bot.</p>;
  }

  const num = (key: keyof BotConfig, label: string, step = "any") => (
    <div className="space-y-2" key={String(key)}>
      <Label>{label}</Label>
      <Input
        type="number"
        step={step}
        value={String(bot[key] ?? "")}
        onChange={(e) => {
          const v = e.target.value;
          updateField(
            key,
            (v === "" ? 0 : Number(v)) as BotConfig[typeof key],
          );
        }}
      />
    </div>
  );

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div>
          <h2 className="text-2xl font-semibold">Cấu hình Bot</h2>
          <p className="text-sm text-muted-foreground">
            {bot.name} — Multi-layer DCA Scalping
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Badge variant={bot.status === "RUNNING" ? "success" : "secondary"}>
            {bot.status}
          </Badge>
          <Badge variant={bot.trading_mode === "SUPER_SAFE" ? "destructive" : "outline"}>
            {bot.trading_mode === "SUPER_SAFE" ? "Siêu an toàn" : "Normal"}
          </Badge>
          <Button variant="outline" onClick={toggleRun}>
            {bot.status === "RUNNING" ? "Dừng bot" : "Bật bot"}
          </Button>
          <Button onClick={handleSave} disabled={saving}>
            {saving ? "Đang lưu…" : "Lưu"}
          </Button>
        </div>
      </div>

      {message && (
        <p className="text-sm text-muted-foreground">{message}</p>
      )}

      <Card>
        <CardHeader>
          <CardTitle>Chế độ giao dịch</CardTitle>
          <CardDescription>
            Normal cho ngày thường; Siêu an toàn khi news hoặc sau daily loss /
            loss guard 16U.
          </CardDescription>
        </CardHeader>
        <CardContent className="grid gap-4 sm:grid-cols-2">
          {TRADING_MODES.map((mode) => {
            const selected = bot.trading_mode === mode.value;
            return (
              <button
                key={mode.value}
                type="button"
                onClick={() => updateField("trading_mode", mode.value)}
                className={`rounded-lg border p-4 text-left transition-colors ${
                  selected
                    ? "border-primary bg-primary/5 ring-2 ring-primary"
                    : "border-border hover:border-primary/50"
                }`}
              >
                <div className="flex items-center justify-between gap-2">
                  <span className="font-semibold">{mode.title}</span>
                  {selected && (
                    <Badge variant="success">Đang dùng</Badge>
                  )}
                </div>
                <p className="mt-2 text-sm text-muted-foreground">
                  {mode.description}
                </p>
              </button>
            );
          })}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Thông tin chung</CardTitle>
        </CardHeader>
        <CardContent className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          <div className="space-y-2">
            <Label>Tên bot</Label>
            <Input
              value={bot.name}
              onChange={(e) => updateField("name", e.target.value)}
            />
          </div>
          {num("symbol", "Symbol")}
          <div className="space-y-2">
            <Label>Khung thời gian (scalping)</Label>
            <select
              className="flex h-9 w-full rounded-md border border-input bg-transparent px-3 py-1 text-sm shadow-sm"
              value={bot.timeframe}
              onChange={(e) => updateField("timeframe", e.target.value)}
            >
              {TIMEFRAMES.map((tf) => (
                <option key={tf} value={tf}>
                  {tf}
                </option>
              ))}
            </select>
          </div>
          {num("bars_lookback", "Bars lookback")}
          {num("risk_per_trade_pct", "Risk % / lệnh (legacy)")}
          {num("magic_number", "Magic number")}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Multi-layer DCA Scalping</CardTitle>
          <CardDescription>
            Tối đa {bot.max_layers ?? 4} lớp (gốc + DCA), spacing 4 giá,
            Joint Close ~$1
          </CardDescription>
        </CardHeader>
        <CardContent className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {num("max_layers", "Max lớp DCA", "1")}
          {num("max_open_positions", "Max lệnh mở (sync)", "1")}
          {num("isolated_leverage", "Đòn bẩy isolated (x)", "1")}
          {num("base_equity_usd", "Vốn gốc tham chiếu (USD)")}
          {num("first_layer_notional_usd", "Notional lớp 1 (USD)")}
          {num("dca_volume_multiplier", "Hệ số volume DCA (Martingale nén)", "0.01")}
          {num("layer_spacing_min", "Khoảng cách nhồi DCA min (giá Vàng)")}
          {num("layer_spacing_max", "Khoảng cách nhồi DCA max (giá Vàng)")}
          {num("basket_tp_min_usd", "Joint TP min — gồng DCA (USD)", "0.1")}
          {num("basket_tp_max_usd", "Joint TP max — gồng DCA (USD)", "0.1")}
          {num("single_tp_min_usd", "Scalp TP min — thuận xu thế (USD)", "0.1")}
          {num("single_tp_max_usd", "Scalp TP max — thuận xu thế (USD)", "0.1")}
          {num("single_tp_distance", "Scalp TP fallback (giá Vàng)")}
          {num("hard_stop_adverse_distance", "Hard stop adverse (giá Vàng)")}
          {num("max_basket_loss_pct", "Max lỗ basket (% balance)", "0.1")}
          {num("max_basket_loss_usd", "Max lỗ basket legacy (USD)", "0.1")}
          {num("counter_trend_max_layers", "Max lớp DCA ngược trend", "1")}
          {num("atr_stop_multiplier", "ATR stop multiplier", "0.1")}
          {num("basket_time_stop_minutes", "Time stop (phút)", "1")}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Tín hiệu &amp; Scalping</CardTitle>
          <CardDescription>
            Ngưỡng vào lệnh và TP/SL legacy (lớp 1 có thể dùng broker TP)
          </CardDescription>
        </CardHeader>
        <CardContent className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {num("signal_threshold", "Signal threshold", "0.01")}
          {num("take_profit_pct", "Take profit % (legacy)")}
          {num("stop_loss_pct", "Stop loss % (legacy, 0 = tắt)")}
          {num("trailing_stop_pct", "Trailing stop %")}
          <div className="flex items-end gap-2">
            <input
              type="checkbox"
              id="trailing"
              checked={bot.trailing_stop_enabled}
              onChange={(e) =>
                updateField("trailing_stop_enabled", e.target.checked)
              }
            />
            <Label htmlFor="trailing">Trailing stop</Label>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Chiến lược (trọng số = 1.0)</CardTitle>
          <CardDescription>
            Donchian + SuperTrend + RSI Midline + EMA21 — entry M15 weighted score
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-6">
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            {num("donchian_period", "Donchian period")}
            {num("donchian_weight", "Donchian weight", "0.01")}
            {num("supertrend_period", "SuperTrend period")}
            {num("supertrend_multiplier", "SuperTrend mult")}
            {num("supertrend_weight", "SuperTrend weight", "0.01")}
            {num("rsi_period", "RSI period")}
            {num("rsi_overbought", "RSI overbought")}
            {num("rsi_oversold", "RSI oversold")}
            {num("rsi_weight", "RSI weight", "0.01")}
            {num("ema_period", "EMA period")}
            {num("ema_weight", "EMA21 weight", "0.01")}
            {num("rsi_swing_lookback", "RSI swing lookback")}
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
