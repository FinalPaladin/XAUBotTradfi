import { cn, formatMoney } from "@/lib/utils";

export function PnlCell({ value }: { value: number | null }) {
  if (value == null) {
    return <span className="text-muted-foreground">—</span>;
  }
  return (
    <span
      className={cn(
        "font-medium tabular-nums",
        value > 0 && "text-emerald-600",
        value < 0 && "text-red-600",
      )}
    >
      {formatMoney(value)}
    </span>
  );
}
