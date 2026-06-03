import {
  AlertTriangle,
  Bot,
  History,
  LayoutDashboard,
  ListOrdered,
  LogOut,
  Server,
} from "lucide-react";
import { NavLink } from "react-router-dom";
import { Button } from "@/components/ui/button";
import { Separator } from "@/components/ui/separator";
import { cn } from "@/lib/utils";
import { logout } from "@/lib/auth";

const navItems = [
  { to: "/", icon: LayoutDashboard, label: "Dashboard" },
  { to: "/positions", icon: ListOrdered, label: "Lệnh hiện tại" },
  { to: "/history", icon: History, label: "Lịch sử vị thế" },
  { to: "/bot-config", icon: Bot, label: "Cấu hình Bot" },
  { to: "/exchanges", icon: Server, label: "Cấu hình sàn" },
  { to: "/logs", icon: AlertTriangle, label: "Log lỗi" },
];

export function AppSidebar() {
  return (
    <aside className="flex h-full w-60 flex-col border-r border-sidebar-border bg-sidebar text-sidebar-foreground">
      <div className="px-5 py-6">
        <p className="text-xs uppercase tracking-widest text-sidebar-primary">
          XAUBot
        </p>
        <h1 className="text-lg font-semibold">TradFi Console</h1>
      </div>
      <Separator className="bg-sidebar-border" />
      <nav className="flex-1 space-y-1 p-3">
        {navItems.map(({ to, icon: Icon, label }) => (
          <NavLink
            key={to}
            to={to}
            end={to === "/"}
            className={({ isActive }) =>
              cn(
                "flex items-center gap-3 rounded-lg px-3 py-2 text-sm transition-colors",
                isActive
                  ? "bg-sidebar-accent text-sidebar-accent-foreground"
                  : "text-sidebar-foreground/80 hover:bg-sidebar-accent/60",
              )
            }
          >
            <Icon className="h-4 w-4 shrink-0" />
            {label}
          </NavLink>
        ))}
      </nav>
      <div className="p-3">
        <Button
          variant="ghost"
          className="w-full justify-start gap-2 text-sidebar-foreground hover:bg-sidebar-accent"
          onClick={() => {
            logout();
            window.location.href = "/login";
          }}
        >
          <LogOut className="h-4 w-4" />
          Đăng xuất
        </Button>
      </div>
    </aside>
  );
}
