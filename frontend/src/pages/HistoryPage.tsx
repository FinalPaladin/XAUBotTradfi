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
import { positionNotional } from "@/lib/trading";
import type { TradeHistory } from "@/lib/types";
import {
  formatDateTime,
  formatMoney,
  formatNumber,
  sideLabel,
} from "@/lib/utils";

export function HistoryPage() {
  const [rows, setRows] = useState<TradeHistory[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    api
      .getHistory(500)
      .then(setRows)
      .finally(() => setLoading(false));
  }, []);

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-2xl font-semibold">Lịch sử vị thế</h2>
        <p className="text-sm text-muted-foreground">
          Lệnh đã đóng với P&amp;L xác thực
        </p>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Lịch sử</CardTitle>
          <CardDescription>
            {loading ? "Đang tải…" : `${rows.length} bản ghi`}
          </CardDescription>
        </CardHeader>
        <CardContent>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>ID lệnh</TableHead>
                <TableHead>Hướng</TableHead>
                <TableHead>Giá vào</TableHead>
                <TableHead>Giá đóng</TableHead>
                <TableHead>Giá trị</TableHead>
                <TableHead>P&amp;L</TableHead>
                <TableHead>Mở</TableHead>
                <TableHead>Đóng</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {rows.length === 0 && !loading && (
                <TableRow>
                  <TableCell
                    colSpan={8}
                    className="text-center text-muted-foreground"
                  >
                    Chưa có lịch sử
                  </TableCell>
                </TableRow>
              )}
              {rows.map((h) => (
                <TableRow key={h.id}>
                  <TableCell className="font-mono text-xs">
                    {h.ticket_id}
                  </TableCell>
                  <TableCell>
                    <Badge
                      variant={
                        h.side === "BUY" ? "success" : "destructive"
                      }
                    >
                      {sideLabel(h.side)}
                    </Badge>
                  </TableCell>
                  <TableCell>{formatNumber(h.entry_price)}</TableCell>
                  <TableCell>{formatNumber(h.exit_price)}</TableCell>
                  <TableCell>
                    {formatMoney(
                      positionNotional(h.volume, h.entry_price),
                    )}
                  </TableCell>
                  <TableCell>
                    <PnlCell value={h.profit_loss} />
                  </TableCell>
                  <TableCell className="text-xs">
                    {formatDateTime(h.opened_at)}
                  </TableCell>
                  <TableCell className="text-xs">
                    {formatDateTime(h.closed_at)}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </CardContent>
      </Card>
    </div>
  );
}
