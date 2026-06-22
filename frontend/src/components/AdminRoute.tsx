import { Navigate, Outlet } from "react-router-dom";
import { useAuth } from "@/contexts/AuthContext";

export function AdminRoute() {
  const { isLoggedIn, isAdminUser } = useAuth();

  if (!isLoggedIn) {
    return <Navigate to="/login" replace />;
  }
  if (!isAdminUser) {
    return <Navigate to="/" replace />;
  }
  return <Outlet />;
}
