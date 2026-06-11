import { useCallback, useEffect, useRef, useState } from "react";
import { ChevronLeft, ChevronRight, RefreshCw } from "lucide-react";
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
import { Label } from "@/components/ui/label";
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
import type { HistoryPnlFilter, OrderSide, TradeHistory } from "@/lib/types";
import { formatLogDateTime, formatLogNumber } from "@/lib/utils";

type DaysFilter = 0 | 7 | 30 | 90;
type SideFilter = "ALL" | OrderSide;
type PageSize = 20 | 50 | 100;

/** ColorHunt-inspired accents */
const filterSelectClass =
  "flex h-9 rounded-md border-2 border-[#45B7D1]/40 bg-[#45B7D1]/5 px-3 py-1 text-sm shadow-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#45B7D1]/50";

function startOfTodayLocalIso() {
  const start = new Date();
  start.setHours(0, 0, 0, 0);
  return start.toISOString();
}

function buildHistoryQuery(
  days: DaysFilter,
  side: SideFilter,
  pnl: HistoryPnlFilter,
  page: number,
  pageSize: PageSize,
) {
  const base = {
    side: side === "ALL" ? undefined : side,
    pnl: pnl === "ALL" ? undefined : pnl,
    page,
    page_size: pageSize,
  } as const;

  if (days === 0) {
    return { ...base, since: startOfTodayLocalIso() };
  }
  return { ...base, days };
}

export function HistoryPage() {
  const [rows, setRows] = useState<TradeHistory[]>([]);
  const [total, setTotal] = useState(0);
  const [totalPnl, setTotalPnl] = useState(0);
  const [page, setPage] = useState(1);
  const [totalPages, setTotalPages] = useState(0);

  const [days, setDays] = useState<DaysFilter>(0);
  const [side, setSide] = useState<SideFilter>("ALL");
  const [pnl, setPnl] = useState<HistoryPnlFilter>("ALL");
  const [pageSize, setPageSize] = useState<PageSize>(20);

  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [syncing, setSyncing] = useState(false);
  const [message, setMessage] = useState("");
  const firstLoad = useRef(true);

  const loadHistory = useCallback(async () => {
    const data = await api.getHistory(
      buildHistoryQuery(days, side, pnl, page, pageSize),
    );
    setRows(data.items ?? []);
    setTotal(data.total ?? 0);
    setTotalPnl(data.total_pnl ?? 0);
    setPage(data.page ?? 1);
    setTotalPages(data.total_pages ?? 0);
  }, [days, side, pnl, page, pageSize]);

  useEffect(() => {
    let cancelled = false;
    if (firstLoad.current) {
      setLoading(true);
      firstLoad.current = false;
    } else {
      setRefreshing(true);
    }

    loadHistory()
      .catch((e) => {
        if (!cancelled) {
          setMessage(e instanceof Error ? e.message : "Tải lịch sử thất bại");
        }
      })
      .finally(() => {
        if (!cancelled) {
          setLoading(false);
          setRefreshing(false);
        }
      });

    return () => {
      cancelled = true;
    };
  }, [loadHistory]);

  async function handleRefresh() {
    setRefreshing(true);
    setMessage("");
    try {
      await loadHistory();
    } catch (e) {
      setMessage(e instanceof Error ? e.message : "Tải lại thất bại");
    } finally {
      setRefreshing(false);
    }
  }

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

  function handleDaysChange(value: DaysFilter) {
    setDays(value);
    setPage(1);
  }

  function handleSideChange(value: SideFilter) {
    setSide(value);
    setPage(1);
  }

  function handlePnlChange(value: HistoryPnlFilter) {
    setPnl(value);
    setPage(1);
  }

  function handlePageSizeChange(value: PageSize) {
    setPageSize(value);
    setPage(1);
  }

  const rangeStart = total === 0 ? 0 : (page - 1) * pageSize + 1;
  const rangeEnd = Math.min(page * pageSize, total);
  const busy = loading || refreshing || syncing;

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h2 className="text-2xl font-semibold">Lịch sử vị thế</h2>
          <p className="text-sm text-muted-foreground">
            Lệnh đã đóng — P&amp;L lấy từ deal MT5 (khớp Exness)
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <Button
            variant="outline"
            disabled={busy}
            onClick={handleRefresh}
            className="border-2 border-[#45B7D1]/50 bg-[#45B7D1]/10 text-[#0984e3] hover:bg-[#45B7D1]/20"
          >
            <RefreshCw
              className={`mr-2 size-4 ${refreshing ? "animate-spin" : ""}`}
            />
            {refreshing ? "Đang tải…" : "Làm mới"}
          </Button>
          <Button
            variant="outline"
            disabled={syncing}
            onClick={handleResync}
            className="border-2 border-[#FFEAA7]/80 bg-[#FFEAA7]/30 text-[#d35400] hover:bg-[#FFEAA7]/50"
          >
            {syncing ? "Đang đồng bộ…" : "Đồng bộ P&L từ Exness"}
          </Button>
        </div>
      </div>

      {message && (
        <p className="text-sm text-muted-foreground">{message}</p>
      )}

      <Card>
        <CardHeader className="space-y-4">
          <div className="flex flex-wrap items-end justify-between gap-4">
            <div>
              <CardTitle>Lịch sử</CardTitle>
              <CardDescription>
                {loading
                  ? "Đang tải…"
                  : `${total} bản ghi · Tổng P&L (đã lọc): ${formatLogNumber(totalPnl)} USD`}
              </CardDescription>
            </div>
          </div>

          <div className="flex flex-wrap items-end gap-4">
            <div className="space-y-1.5">
              <Label htmlFor="history-days">Khoảng ngày</Label>
              <select
                id="history-days"
                className={filterSelectClass}
                value={days}
                disabled={busy}
                onChange={(e) =>
                  handleDaysChange(Number(e.target.value) as DaysFilter)
                }
              >
                <option value={0}>Hôm nay</option>
                <option value={7}>7 ngày</option>
                <option value={30}>30 ngày</option>
                <option value={90}>90 ngày</option>
              </select>
            </div>

            <div className="space-y-1.5">
              <Label htmlFor="history-side">Chiều lệnh</Label>
              <select
                id="history-side"
                className={filterSelectClass}
                value={side}
                disabled={busy}
                onChange={(e) =>
                  handleSideChange(e.target.value as SideFilter)
                }
              >
                <option value="ALL">Tất cả</option>
                <option value="BUY">LONG</option>
                <option value="SELL">SHORT</option>
              </select>
            </div>

            <div className="space-y-1.5">
              <Label htmlFor="history-pnl">Lời / Lỗ</Label>
              <select
                id="history-pnl"
                className={filterSelectClass}
                value={pnl}
                disabled={busy}
                onChange={(e) =>
                  handlePnlChange(e.target.value as HistoryPnlFilter)
                }
              >
                <option value="ALL">Tất cả</option>
                <option value="WIN">Lời</option>
                <option value="LOSS">Lỗ</option>
              </select>
            </div>

            <div className="space-y-1.5">
              <Label htmlFor="history-page-size">Số dòng / trang</Label>
              <select
                id="history-page-size"
                className={filterSelectClass}
                value={pageSize}
                disabled={busy}
                onChange={(e) =>
                  handlePageSizeChange(Number(e.target.value) as PageSize)
                }
              >
                <option value={20}>20</option>
                <option value={50}>50</option>
                <option value={100}>100</option>
              </select>
            </div>
          </div>
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
                    Không có bản ghi phù hợp bộ lọc
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

          <div className="mt-4 flex flex-wrap items-center justify-between gap-3">
            <p className="text-sm text-muted-foreground">
              {total === 0
                ? "Không có dữ liệu"
                : `Hiển thị ${rangeStart}–${rangeEnd} / ${total} bản ghi`}
            </p>
            <div className="flex items-center gap-2">
              <Button
                variant="outline"
                size="sm"
                disabled={busy || page <= 1}
                onClick={() => setPage((p) => Math.max(1, p - 1))}
                className="border-[#96CEB4]/60 bg-[#96CEB4]/15 hover:bg-[#96CEB4]/30"
              >
                <ChevronLeft className="size-4" />
                Trước
              </Button>
              <span className="min-w-[88px] text-center text-sm tabular-nums">
                Trang {totalPages === 0 ? 0 : page} / {totalPages}
              </span>
              <Button
                variant="outline"
                size="sm"
                disabled={busy || page >= totalPages || totalPages === 0}
                onClick={() => setPage((p) => p + 1)}
                className="border-[#96CEB4]/60 bg-[#96CEB4]/15 hover:bg-[#96CEB4]/30"
              >
                Sau
                <ChevronRight className="size-4" />
              </Button>
            </div>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
