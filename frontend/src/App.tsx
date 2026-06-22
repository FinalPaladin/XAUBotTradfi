import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { AdminRoute } from "@/components/AdminRoute";
import { AppLayout } from "@/components/layout/AppLayout";
import { ProtectedRoute } from "@/components/ProtectedRoute";
import { AdminUsersPage } from "@/pages/AdminUsersPage";
import { BotConfigPage } from "@/pages/BotConfigPage";
import { ExchangesPage } from "@/pages/ExchangesPage";
import { HistoryPage } from "@/pages/HistoryPage";
import { HomePage } from "@/pages/HomePage";
import { LoginPage } from "@/pages/LoginPage";
import { LogsPage } from "@/pages/LogsPage";
import { OpenPositionsPage } from "@/pages/OpenPositionsPage";

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/login" element={<LoginPage />} />
        <Route element={<ProtectedRoute />}>
          <Route element={<AppLayout />}>
            <Route index element={<HomePage />} />
            <Route path="positions" element={<OpenPositionsPage />} />
            <Route path="history" element={<HistoryPage />} />
            <Route path="bot-config" element={<BotConfigPage />} />
            <Route path="exchanges" element={<ExchangesPage />} />
            <Route path="logs" element={<LogsPage />} />
          </Route>
          <Route element={<AdminRoute />}>
            <Route element={<AppLayout />}>
              <Route path="admin/users" element={<AdminUsersPage />} />
            </Route>
          </Route>
        </Route>
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </BrowserRouter>
  );
}
