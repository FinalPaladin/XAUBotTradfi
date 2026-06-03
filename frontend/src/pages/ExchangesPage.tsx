import { useEffect, useState } from "react";
import { Badge } from "@/components/ui/badge";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { api } from "@/lib/api";
import type { ExchangeConfig } from "@/lib/types";

export function ExchangesPage() {
  const [exchanges, setExchanges] = useState<ExchangeConfig[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    api
      .getExchanges()
      .then(setExchanges)
      .finally(() => setLoading(false));
    const id = setInterval(() => api.getExchanges().then(setExchanges), 30000);
    return () => clearInterval(id);
  }, []);

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-2xl font-semibold">Cấu hình sàn</h2>
        <p className="text-sm text-muted-foreground">
          Kết nối MT5 / Bybit TradFi (đọc từ backend .env)
        </p>
      </div>

      {loading && (
        <p className="text-muted-foreground">Đang tải…</p>
      )}

      <div className="grid gap-4 md:grid-cols-2">
        {exchanges.map((ex) => (
          <Card key={ex.id}>
            <CardHeader>
              <div className="flex items-center justify-between">
                <CardTitle>{ex.name}</CardTitle>
                <Badge variant={ex.connected ? "success" : "destructive"}>
                  {ex.connected ? "Đã kết nối" : "Chưa kết nối"}
                </Badge>
              </div>
              <CardDescription>{ex.platform}</CardDescription>
            </CardHeader>
            <CardContent className="space-y-2 text-sm">
              <div className="flex justify-between">
                <span className="text-muted-foreground">Server</span>
                <span className="font-medium">{ex.server ?? "—"}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-muted-foreground">Login</span>
                <span className="font-mono">{ex.login ?? "—"}</span>
              </div>
              {ex.error && (
                <p className="rounded-md bg-destructive/10 p-2 text-destructive">
                  {ex.error}
                </p>
              )}
              {ex.extra.account != null && (
                <pre className="mt-2 max-h-40 overflow-auto rounded-md bg-muted p-2 text-xs">
                  {JSON.stringify(ex.extra.account, null, 2)}
                </pre>
              )}
              {ex.extra.mt5_path != null && (
                <p className="text-xs text-muted-foreground break-all">
                  Path: {String(ex.extra.mt5_path)}
                </p>
              )}
            </CardContent>
          </Card>
        ))}
      </div>
    </div>
  );
}
