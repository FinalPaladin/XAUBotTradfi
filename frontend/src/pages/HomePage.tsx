import { useEffect, useState } from "react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { StatCard } from "@/components/StatCard";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { api } from "@/lib/api";
import { buildDailyPnlSeries, todayPnl } from "@/lib/trading";
import { formatMoney } from "@/lib/utils";

export function HomePage() {
  const [loading, setLoading] = useState(true);
  const [openCount, setOpenCount] = useState(0);
  const [winCount, setWinCount] = useState(0);
  const [lossCount, setLossCount] = useState(0);
  const [todayProfit, setTodayProfit] = useState(0);
  const [chartData, setChartData] = useState<
    { date: string; pnl: number; cumulative: number }[]
  >([]);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      try {
        const [status, history] = await Promise.all([
          api.getStatus(),
          api.getHistory(500),
        ]);
        if (cancelled) return;
        setOpenCount(status.open_positions.length);
        const wins = history.filter((h) => h.profit_loss > 0).length;
        const losses = history.filter((h) => h.profit_loss < 0).length;
        setWinCount(wins);
        setLossCount(losses);
        setTodayProfit(todayPnl(history));
        setChartData(buildDailyPnlSeries(history, 30));
      } finally {
        if (!cancelled) setLoading(false);
      }
    }
    load();
    const id = setInterval(load, 15000);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, []);

  if (loading) {
    return <p className="text-muted-foreground">Đang tải dashboard…</p>;
  }

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-2xl font-semibold">Dashboard</h2>
        <p className="text-sm text-muted-foreground">
          Tổng quan lệnh và lợi nhuận 30 ngày gần nhất
        </p>
      </div>

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <StatCard title="Lệnh đang mở" value={String(openCount)} />
        <StatCard
          title="Lệnh lời (đã đóng)"
          value={String(winCount)}
          tone="profit"
        />
        <StatCard
          title="Lệnh lỗ (đã đóng)"
          value={String(lossCount)}
          tone="loss"
        />
        <StatCard
          title="Lời hôm nay"
          value={formatMoney(todayProfit)}
          tone={todayProfit >= 0 ? "profit" : "loss"}
        />
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle>P&amp;L theo ngày (30 ngày)</CardTitle>
            <CardDescription>Lợi nhuận đóng lệnh mỗi ngày</CardDescription>
          </CardHeader>
          <CardContent className="h-72">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={chartData}>
                <CartesianGrid strokeDasharray="3 3" className="stroke-border" />
                <XAxis dataKey="date" tick={{ fontSize: 11 }} />
                <YAxis tick={{ fontSize: 11 }} />
                <Tooltip
                  formatter={(v) => formatMoney(Number(v ?? 0))}
                  labelFormatter={(l) => `Ngày ${l}`}
                />
                <Bar dataKey="pnl" fill="var(--color-primary)" radius={[4, 4, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Lợi nhuận tích lũy</CardTitle>
            <CardDescription>Cumulative P&amp;L 30 ngày</CardDescription>
          </CardHeader>
          <CardContent className="h-72">
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={chartData}>
                <CartesianGrid strokeDasharray="3 3" className="stroke-border" />
                <XAxis dataKey="date" tick={{ fontSize: 11 }} />
                <YAxis tick={{ fontSize: 11 }} />
                <Tooltip
                  formatter={(v) => formatMoney(Number(v ?? 0))}
                  labelFormatter={(l) => `Ngày ${l}`}
                />
                <Line
                  type="monotone"
                  dataKey="cumulative"
                  stroke="var(--color-primary)"
                  strokeWidth={2}
                  dot={false}
                />
              </LineChart>
            </ResponsiveContainer>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
