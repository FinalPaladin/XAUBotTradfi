import { useCallback, useEffect, useState } from "react";
import {
  LogPnlCell,
  LogValueCell,
  PositionSideCell,
  TicketCell,
} from "@/components/TradeLogCells";
import { Button } from "@/components/ui/button";
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
  unrealizedPnlFromLive,
} from "@/lib/trading";
import type { TradePosition } from "@/lib/types";
import { formatLogDateTime, formatLogNumber } from "@/lib/utils";

export function OpenPositionsPage() {
  const [positions, setPositions] = useState<TradePosition[]>([]);
  const [ticks, setTicks] = useState<Record<string, number | null>>({});
  const [live, setLive] = useState<
    Record<string, { price_current: number; profit: number; swap?: number }>
  >({});
  const [loading, setLoading] = useState(true);
  const [closingId, setClosingId] = useState<number | null>(null);
  const [closingAll, setClosingAll] = useState(false);
  const [message, setMessage] = useState("");

  const load = useCallback(async () => {
    const status = await api.getStatus();
    setPositions(status.open_positions);
    setTicks(status.meta.symbol_ticks ?? {});
    setLive(status.meta.position_live ?? {});
  }, []);

  useEffect(() => {
    let cancelled = false;
    async function init() {
      try {
        if (!cancelled) await load();
      } finally {
        if (!cancelled) setLoading(false);
      }
    }
    init();
    const id = setInterval(load, 3000);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, [load]);

  async function handleCloseOne(positionId: number) {
    if (!window.confirm("Đóng lệnh này tại giá Market?")) return;
    setClosingId(positionId);
    setMessage("");
    try {
      await api.closePosition(positionId);
      setMessage("Đã đóng lệnh tại giá Market");
      await load();
    } catch (e) {
      setMessage(e instanceof Error ? e.message : "Không đóng được lệnh");
    } finally {
      setClosingId(null);
    }
  }

  async function handleCloseAll() {
    if (positions.length === 0) return;
    if (!window.confirm(`Đóng tất cả ${positions.length} lệnh tại giá Market?`)) {
      return;
    }
    setClosingAll(true);
    setMessage("");
    try {
      await api.closeAllPositions();
      setMessage("Đã đóng tất cả lệnh tại giá Market");
      await load();
    } catch (e) {
      setMessage(e instanceof Error ? e.message : "Không đóng được lệnh");
    } finally {
      setClosingAll(false);
    }
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h2 className="text-2xl font-semibold">Lệnh hiện tại</h2>
          <p className="text-sm text-muted-foreground">
            Vị thế đang mở trên sàn — định dạng log giao dịch
          </p>
        </div>
        <Button
          variant="destructive"
          disabled={closingAll || positions.length === 0}
          onClick={handleCloseAll}
        >
          {closingAll ? "Đang đóng…" : "Đóng tất cả lệnh"}
        </Button>
      </div>

      {message && (
        <p className="text-sm text-muted-foreground">{message}</p>
      )}

      <Card>
        <CardHeader>
          <CardTitle>Danh sách lệnh</CardTitle>
          <CardDescription>
            {loading ? "Đang tải…" : `${positions.length} lệnh`}
          </CardDescription>
        </CardHeader>
        <CardContent className="overflow-x-auto">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Vị Thế</TableHead>
                <TableHead>Giá Vào Lệnh</TableHead>
                <TableHead>Giá thị trường</TableHead>
                <TableHead>P&amp;L chưa xác thực</TableHead>
                <TableHead>Giá trị</TableHead>
                <TableHead>Đã Mở Vào</TableHead>
                <TableHead>Vé</TableHead>
                <TableHead className="text-right">Thao tác</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {positions.length === 0 && !loading && (
                <TableRow>
                  <TableCell
                    colSpan={8}
                    className="text-center text-muted-foreground"
                  >
                    Không có lệnh đang mở
                  </TableCell>
                </TableRow>
              )}
              {positions.map((p) => {
                const mkt = marketPrice(p, ticks, live);
                const pnlLive = unrealizedPnlFromLive(p, live);
                const pnl =
                  pnlLive ??
                  unrealizedPnl(p.side, p.entry_price, mkt, p.volume);
                return (
                  <TableRow key={p.id}>
                    <TableCell>
                      <PositionSideCell symbol={p.symbol} side={p.side} />
                      {(p.layer_index ?? 0) > 0 && (
                        <p className="mt-1 text-xs text-muted-foreground">
                          Lớp DCA {(p.layer_index ?? 0) + 1}
                        </p>
                      )}
                    </TableCell>
                    <TableCell className="font-semibold tabular-nums">
                      {formatLogNumber(p.entry_price)}
                    </TableCell>
                    <TableCell className="font-semibold tabular-nums">
                      {mkt != null ? formatLogNumber(mkt) : "—"}
                    </TableCell>
                    <TableCell>
                      <LogPnlCell value={pnl} />
                    </TableCell>
                    <TableCell>
                      <LogValueCell
                        value={positionNotional(p.volume, p.entry_price)}
                      />
                    </TableCell>
                    <TableCell className="whitespace-nowrap text-sm tabular-nums text-muted-foreground">
                      {formatLogDateTime(p.opened_at)}
                    </TableCell>
                    <TableCell>
                      <TicketCell ticketId={p.ticket_id} />
                    </TableCell>
                    <TableCell className="text-right">
                      <Button
                        variant="outline"
                        size="sm"
                        disabled={closingId === p.id || closingAll}
                        onClick={() => handleCloseOne(p.id)}
                      >
                        {closingId === p.id ? "Đang đóng…" : "Đóng"}
                      </Button>
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
