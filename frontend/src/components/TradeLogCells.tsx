import { Copy } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { cn, formatLogNumber, sideLabel } from "@/lib/utils";

export function PositionSideCell({
  symbol,
  side,
}: {
  symbol: string;
  side: string;
}) {
  return (
    <div className="space-y-1">
      <div className="font-semibold text-foreground">{symbol}</div>
      <Badge
        className={cn(
          "border-0 text-xs font-semibold text-white",
          side === "BUY"
            ? "bg-[#4ECDC4] hover:bg-[#4ECDC4]/90"
            : "bg-[#FF6B6B] hover:bg-[#FF6B6B]/90",
        )}
      >
        {sideLabel(side)}
      </Badge>
    </div>
  );
}

export function LogPnlCell({ value }: { value: number | null }) {
  if (value == null) {
    return <span className="text-muted-foreground">—</span>;
  }
  return (
    <span
      className={cn(
        "font-semibold tabular-nums text-foreground",
        value > 0 && "text-[#00b894]",
        value < 0 && "text-[#d63031]",
      )}
    >
      {formatLogNumber(value)}
    </span>
  );
}

export function TicketCell({ ticketId }: { ticketId: string }) {
  async function copy() {
    try {
      await navigator.clipboard.writeText(ticketId);
    } catch {
      /* ignore */
    }
  }

  return (
    <div className="flex items-center gap-2">
      <span className="font-mono text-sm tabular-nums text-foreground">
        {ticketId}
      </span>
      <button
        type="button"
        onClick={copy}
        className="text-muted-foreground transition-colors hover:text-foreground"
        title="Copy vé"
      >
        <Copy className="h-3.5 w-3.5" />
      </button>
    </div>
  );
}

export function LogValueCell({ value }: { value: number }) {
  return (
    <span className="font-semibold tabular-nums text-foreground">
      {formatLogNumber(value)}
    </span>
  );
}
