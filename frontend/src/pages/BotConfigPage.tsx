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
import type { BotConfig } from "@/lib/types";

export function BotConfigPage() {
  const [bot, setBot] = useState<BotConfig | null>(null);
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState("");

  useEffect(() => {
    api.getConfigs().then((list) => setBot(list[0] ?? null));
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
      const { id, created_at, updated_at, ...payload } = bot;
      const saved = await api.updateConfig({ ...payload, id });
      setBot(saved);
      setMessage("Đã lưu cấu hình");
    } catch (e) {
      setMessage(e instanceof Error ? e.message : "Lỗi lưu");
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
          <p className="text-sm text-muted-foreground">{bot.name}</p>
        </div>
        <div className="flex items-center gap-2">
          <Badge variant={bot.status === "RUNNING" ? "success" : "secondary"}>
            {bot.status}
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
          {num("timeframe", "Khung thời gian")}
          {num("bars_lookback", "Bars lookback")}
          {num("risk_per_trade_pct", "Risk % / lệnh")}
          {num("max_open_positions", "Max lệnh mở")}
          {num("magic_number", "Magic number")}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Risk &amp; TP/SL</CardTitle>
        </CardHeader>
        <CardContent className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {num("take_profit_pct", "Take profit %")}
          {num("stop_loss_pct", "Stop loss %")}
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
          {num("signal_threshold", "Signal threshold", "0.01")}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Chiến lược (trọng số = 1.0)</CardTitle>
          <CardDescription>
            Donchian + SuperTrend + RSI
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
            {num("rsi_swing_lookback", "RSI swing lookback")}
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
