import * as React from "react";
import { cn } from "@/lib/utils";

function Checkbox({
  className,
  ...props
}: React.ComponentProps<"input">) {
  return (
    <input
      type="checkbox"
      className={cn(
        "h-4 w-4 shrink-0 rounded border border-input accent-primary",
        className,
      )}
      {...props}
    />
  );
}

export { Checkbox };
