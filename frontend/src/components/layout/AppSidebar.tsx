import {
  AlertTriangle,
  Bot,
  History,
  LayoutDashboard,
  ListOrdered,
  Server,
  Users,
} from "lucide-react";
import { NavLink } from "react-router-dom";
import { Separator } from "@/components/ui/separator";
import { cn } from "@/lib/utils";
import { useAuth } from "@/contexts/AuthContext";

const navItems = [
  { to: "/", icon: LayoutDashboard, label: "Dashboard" },
  { to: "/positions", icon: ListOrdered, label: "Lệnh hiện tại" },
  { to: "/history", icon: History, label: "Lịch sử vị thế" },
  { to: "/bot-config", icon: Bot, label: "Cấu hình Bot" },
  { to: "/exchanges", icon: Server, label: "Cấu hình sàn" },
  { to: "/logs", icon: AlertTriangle, label: "Log lỗi" },
];

export function AppSidebar() {
  const { isAdminUser } = useAuth();

  const items = isAdminUser
    ? [...navItems, { to: "/admin/users", icon: Users, label: "Quản lý Account" }]
    : navItems;

  return (
    <aside
      className="flex h-screen min-h-screen w-60 shrink-0 flex-col border-r border-sidebar-border bg-sidebar font-[Inter,sans-serif] text-white"
      style={{ fontFamily: "'Inter', sans-serif" }}
    >
      <div className="px-5 py-6">
        <p className="text-xs font-medium uppercase tracking-widest text-white/75">
          XAUBot
        </p>
        <h1 className="text-lg font-semibold text-white">TradFi Console</h1>
      </div>
      <Separator className="bg-sidebar-border" />
      <nav className="flex-1 space-y-1 overflow-y-auto p-3">
        {items.map(({ to, icon: Icon, label }) => (
          <NavLink
            key={to}
            to={to}
            end={to === "/"}
            className={({ isActive }) =>
              cn(
                "flex items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium text-white transition-colors",
                isActive
                  ? "bg-white/20 text-white"
                  : "text-white/85 hover:bg-white/10 hover:text-white",
              )
            }
          >
            <Icon className="h-4 w-4 shrink-0" />
            {label}
          </NavLink>
        ))}
      </nav>
    </aside>
  );
}
