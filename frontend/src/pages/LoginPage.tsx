import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { login } from "@/lib/auth";

export function LoginPage() {
  const navigate = useNavigate();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (login(username.trim(), password)) {
      navigate("/", { replace: true });
      return;
    }
    setError("Sai tên đăng nhập hoặc mật khẩu");
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-gradient-to-br from-amber-50 via-white to-zinc-100 p-4">
      <Card className="w-full max-w-md">
        <CardHeader>
          <CardTitle>XAUBot TradFi</CardTitle>
          <CardDescription>Đăng nhập quản trị hệ thống bot</CardDescription>
        </CardHeader>
        <CardContent>
          <form onSubmit={handleSubmit} className="space-y-4">
            <div className="space-y-2">
              <Label htmlFor="username">Tên đăng nhập</Label>
              <Input
                id="username"
                autoComplete="username"
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                placeholder="admin"
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="password">Mật khẩu</Label>
              <Input
                id="password"
                type="password"
                autoComplete="current-password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
              />
            </div>
            {error && (
              <p className="text-sm text-destructive">{error}</p>
            )}
            <Button type="submit" className="w-full">
              Đăng nhập
            </Button>
          </form>
        </CardContent>
      </Card>
    </div>
  );
}
