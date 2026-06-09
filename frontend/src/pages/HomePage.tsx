import { useCallback, useEffect, useRef, useState } from "react";
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
import { Label } from "@/components/ui/label";
import { api } from "@/lib/api";
import { buildDailyPnlSeries, todayPnl } from "@/lib/trading";
import { formatMoney } from "@/lib/utils";

type DaysFilter = 7 | 30 | 90;

const selectClass =
  "flex h-9 rounded-md border border-input bg-transparent px-3 py-1 text-sm shadow-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring";

export function HomePage() {
  const [days, setDays] = useState<DaysFilter>(7);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState("");
  const [openCount, setOpenCount] = useState(0);
  const [winCount, setWinCount] = useState(0);
  const [lossCount, setLossCount] = useState(0);
  const [todayProfit, setTodayProfit] = useState(0);
  const [chartData, setChartData] = useState<
    { date: string; pnl: number; cumulative: number }[]
  >([]);
  const firstLoad = useRef(true);

  const loadDashboard = useCallback(async () => {
    setError("");
    const status = await api.getStatus();
    setOpenCount(status.open_positions.length);

    const historyPage = await api.getHistory({
      days,
      page: 1,
      page_size: 100,
    });
    const history = historyPage.items;
    const wins = history.filter((h) => h.profit_loss > 0).length;
    const losses = history.filter((h) => h.profit_loss < 0).length;
    setWinCount(wins);
    setLossCount(losses);
    setTodayProfit(todayPnl(history));
    setChartData(buildDailyPnlSeries(history, days));
  }, [days]);

  useEffect(() => {
    let cancelled = false;
    if (firstLoad.current) {
      setLoading(true);
      firstLoad.current = false;
    } else {
      setRefreshing(true);
    }

    loadDashboard()
      .catch((e) => {
        if (!cancelled) {
          setError(
            e instanceof Error ? e.message : "Không tải được dữ liệu dashboard",
          );
        }
      })
      .finally(() => {
        if (!cancelled) {
          setLoading(false);
          setRefreshing(false);
        }
      });

    const id = window.setInterval(() => {
      loadDashboard().catch(() => {});
    }, 15000);

    return () => {
      cancelled = true;
      window.clearInterval(id);
    };
  }, [loadDashboard]);

  if (loading) {
    return <p className="text-muted-foreground">Đang tải dashboard…</p>;
  }

  const busy = loading || refreshing;

  return (
    <div className="space-y-6">
      {error ? (
        <p className="rounded-md border border-destructive/50 bg-destructive/10 px-3 py-2 text-sm text-destructive">
          {error}
        </p>
      ) : null}
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h2 className="text-2xl font-semibold">Dashboard</h2>
          <p className="text-sm text-muted-foreground">
            Tổng quan lệnh và lợi nhuận {days} ngày gần nhất
            {refreshing ? " · Đang cập nhật…" : ""}
          </p>
        </div>
        <div className="space-y-1.5">
          <Label htmlFor="dashboard-days">Khoảng ngày</Label>
          <select
            id="dashboard-days"
            className={selectClass}
            value={days}
            disabled={busy}
            onChange={(e) => setDays(Number(e.target.value) as DaysFilter)}
          >
            <option value={7}>7 ngày</option>
            <option value={30}>30 ngày</option>
            <option value={90}>90 ngày</option>
          </select>
        </div>
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
            <CardTitle>P&amp;L theo ngày ({days} ngày)</CardTitle>
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
            <CardDescription>Cumulative P&amp;L {days} ngày</CardDescription>
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
