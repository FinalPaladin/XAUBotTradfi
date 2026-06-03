import { useEffect, useState } from "react";
import { PnlCell } from "@/components/PnlCell";
import { Badge } from "@/components/ui/badge";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { api } from "@/lib/api";
import {
  marketPrice,
  positionNotional,
  unrealizedPnl,
} from "@/lib/trading";
import type { TradePosition } from "@/lib/types";
import { formatMoney, formatNumber, sideLabel } from "@/lib/utils";

export function OpenPositionsPage() {
  const [positions, setPositions] = useState<TradePosition[]>([]);
  const [ticks, setTicks] = useState<Record<string, number | null>>({});
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      try {
        const status = await api.getStatus();
        if (!cancelled) {
          setPositions(status.open_positions);
          setTicks(status.meta.symbol_ticks ?? {});
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    }
    load();
    const id = setInterval(load, 10000);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, []);

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-2xl font-semibold">Lệnh hiện tại</h2>
        <p className="text-sm text-muted-foreground">
          Vị thế đang mở trên sàn
        </p>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Danh sách lệnh</CardTitle>
          <CardDescription>
            {loading ? "Đang tải…" : `${positions.length} lệnh`}
          </CardDescription>
        </CardHeader>
        <CardContent>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Hướng</TableHead>
                <TableHead>Symbol</TableHead>
                <TableHead>Giá vào</TableHead>
                <TableHead>Giá thị trường</TableHead>
                <TableHead>Giá trị lệnh</TableHead>
                <TableHead>P&amp;L chưa xác thực</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {positions.length === 0 && !loading && (
                <TableRow>
                  <TableCell colSpan={6} className="text-center text-muted-foreground">
                    Không có lệnh đang mở
                  </TableCell>
                </TableRow>
              )}
              {positions.map((p) => {
                const mkt = marketPrice(p, ticks);
                const pnl = unrealizedPnl(p.side, p.entry_price, mkt, p.volume);
                return (
                  <TableRow key={p.id}>
                    <TableCell>
                      <Badge
                        variant={
                          p.side === "BUY" ? "success" : "destructive"
                        }
                      >
                        {sideLabel(p.side)}
                      </Badge>
                    </TableCell>
                    <TableCell>{p.symbol}</TableCell>
                    <TableCell>{formatNumber(p.entry_price)}</TableCell>
                    <TableCell>
                      {mkt != null ? formatNumber(mkt) : "—"}
                    </TableCell>
                    <TableCell>
                      {formatMoney(positionNotional(p.volume, p.entry_price))}
                    </TableCell>
                    <TableCell>
                      <PnlCell value={pnl} />
                    </TableCell>
                  </TableRow>
                );
              })}
            </TableBody>
          </Table>
        </CardContent>
      </Card>
    </div>
  );
}
