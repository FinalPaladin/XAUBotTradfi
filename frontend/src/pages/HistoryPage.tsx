import { useEffect, useMemo, useState } from "react";
import { Button } from "@/components/ui/button";
import {
  LogPnlCell,
  LogValueCell,
  PositionSideCell,
  TicketCell,
} from "@/components/TradeLogCells";
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
import { formatLogDateTime, formatLogNumber } from "@/lib/utils";

export function HistoryPage() {
  const [rows, setRows] = useState<TradeHistory[]>([]);
  const [loading, setLoading] = useState(true);
  const [syncing, setSyncing] = useState(false);
  const [message, setMessage] = useState("");

  const totalPnl = useMemo(
    () => rows.reduce((s, h) => s + h.profit_loss, 0),
    [rows],
  );

  function loadHistory() {
    return api.getHistory(500).then(setRows);
  }

  useEffect(() => {
    loadHistory().finally(() => setLoading(false));
  }, []);

  async function handleResync() {
    setSyncing(true);
    setMessage("");
    try {
      const res = await api.resyncHistoryPnl();
      await loadHistory();
      const updated = res.detail?.updated ?? 0;
      setMessage(`Đã đồng bộ ${updated} lệnh từ MT5/Exness`);
    } catch (e) {
      setMessage(e instanceof Error ? e.message : "Đồng bộ thất bại");
    } finally {
      setSyncing(false);
    }
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h2 className="text-2xl font-semibold">Lịch sử vị thế</h2>
          <p className="text-sm text-muted-foreground">
            Lệnh đã đóng — P&amp;L lấy từ deal MT5 (khớp Exness)
          </p>
        </div>
        <Button variant="outline" disabled={syncing} onClick={handleResync}>
          {syncing ? "Đang đồng bộ…" : "Đồng bộ P&L từ Exness"}
        </Button>
      </div>

      {message && (
        <p className="text-sm text-muted-foreground">{message}</p>
      )}

      <Card>
        <CardHeader>
          <CardTitle>Lịch sử</CardTitle>
          <CardDescription>
            {loading
              ? "Đang tải…"
              : `${rows.length} bản ghi · Tổng P&L: ${formatLogNumber(totalPnl)} USD`}
          </CardDescription>
        </CardHeader>
        <CardContent className="overflow-x-auto">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Vị Thế</TableHead>
                <TableHead>Giá Vào Lệnh</TableHead>
                <TableHead>Giá đóng vị thế</TableHead>
                <TableHead>P&amp;L Xác Thực</TableHead>
                <TableHead>Giá trị</TableHead>
                <TableHead>Đã Mở Vào</TableHead>
                <TableHead>Đã Đóng Vào</TableHead>
                <TableHead>Vé</TableHead>
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
                  <TableCell>
                    <PositionSideCell symbol={h.symbol} side={h.side} />
                  </TableCell>
                  <TableCell className="font-semibold tabular-nums">
                    {formatLogNumber(h.entry_price)}
                  </TableCell>
                  <TableCell className="font-semibold tabular-nums">
                    {formatLogNumber(h.exit_price)}
                  </TableCell>
                  <TableCell>
                    <LogPnlCell value={h.profit_loss} />
                  </TableCell>
                  <TableCell>
                    <LogValueCell
                      value={positionNotional(h.volume, h.entry_price)}
                    />
                  </TableCell>
                  <TableCell className="whitespace-nowrap text-sm tabular-nums text-muted-foreground">
                    {formatLogDateTime(h.opened_at)}
                  </TableCell>
                  <TableCell className="whitespace-nowrap text-sm tabular-nums text-muted-foreground">
                    {formatLogDateTime(h.closed_at)}
                  </TableCell>
                  <TableCell>
                    <TicketCell ticketId={h.ticket_id} />
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
