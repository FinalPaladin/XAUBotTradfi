import { useEffect, useState } from "react";
import { Badge } from "@/components/ui/badge";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { ScrollArea } from "@/components/ui/scroll-area";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { api } from "@/lib/api";
import type { SystemLog } from "@/lib/types";
import { formatDateTime } from "@/lib/utils";

function levelVariant(level: string) {
  if (level === "ERROR") return "destructive" as const;
  if (level === "WARNING") return "warning" as const;
  return "secondary" as const;
}

export function LogsPage() {
  const [logs, setLogs] = useState<SystemLog[]>([]);
  const [errorsOnly, setErrorsOnly] = useState(true);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    setLoading(true);
    api
      .getLogs(errorsOnly ? "ERROR" : undefined)
      .then(setLogs)
      .finally(() => setLoading(false));
    const id = setInterval(() => {
      api.getLogs(errorsOnly ? "ERROR" : undefined).then(setLogs);
    }, 20000);
    return () => clearInterval(id);
  }, [errorsOnly]);

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div>
          <h2 className="text-2xl font-semibold">Log hệ thống</h2>
          <p className="text-sm text-muted-foreground">
            Lỗi API, MT5 và bot worker
          </p>
        </div>
        <label className="flex items-center gap-2 text-sm">
          <input
            type="checkbox"
            checked={errorsOnly}
            onChange={(e) => setErrorsOnly(e.target.checked)}
          />
          Chỉ hiển thị ERROR
        </label>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Danh sách log</CardTitle>
          <CardDescription>
            {loading ? "Đang tải…" : `${logs.length} dòng`}
          </CardDescription>
        </CardHeader>
        <CardContent>
          <ScrollArea className="h-[calc(100vh-16rem)]">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Thời gian</TableHead>
                  <TableHead>Level</TableHead>
                  <TableHead>Source</TableHead>
                  <TableHead>Bot</TableHead>
                  <TableHead>Message</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {logs.length === 0 && !loading && (
                  <TableRow>
                    <TableCell
                      colSpan={5}
                      className="text-center text-muted-foreground"
                    >
                      Không có log
                    </TableCell>
                  </TableRow>
                )}
                {logs.map((log) => (
                  <TableRow key={log.id}>
                    <TableCell className="whitespace-nowrap text-xs">
                      {formatDateTime(log.created_at)}
                    </TableCell>
                    <TableCell>
                      <Badge variant={levelVariant(log.level)}>
                        {log.level}
                      </Badge>
                    </TableCell>
                    <TableCell>{log.source}</TableCell>
                    <TableCell>{log.bot_id ?? "—"}</TableCell>
                    <TableCell className="max-w-xl break-words text-sm">
                      {log.message}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </ScrollArea>
        </CardContent>
      </Card>
    </div>
  );
}
