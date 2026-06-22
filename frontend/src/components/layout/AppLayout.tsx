import { Outlet } from "react-router-dom";
import { AppSidebar } from "./AppSidebar";
import { UserMenu } from "./UserMenu";
import { Settings } from "lucide-react";

export function AppLayout() {
  return (
    <div className="flex h-screen min-h-screen overflow-hidden">
      <AppSidebar />
      <div className="flex min-h-0 flex-1 flex-col overflow-hidden">
        <header className="flex h-14 items-center justify-between border-b bg-card px-6">
          <div className="flex items-center gap-2 text-sm text-muted-foreground">
            <Settings className="h-4 w-4" />
            <span>Bybit TradFi · XAUUSD</span>
          </div>
          <UserMenu />
        </header>
        <main className="flex-1 overflow-auto p-6">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
