import { useState } from "react";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import { Separator } from "@/components/ui/separator";
import { useAuth } from "@/contexts/AuthContext";
import { api } from "@/lib/api";
import { logout } from "@/lib/auth";

interface AccountInfoModalProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

export function AccountInfoModal({ open, onOpenChange }: AccountInfoModalProps) {
  const { user } = useAuth();
  const [oldPassword, setOldPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");
  const [loading, setLoading] = useState(false);

  function resetForm() {
    setOldPassword("");
    setNewPassword("");
    setConfirmPassword("");
    setError("");
    setSuccess("");
  }

  async function handleChangePassword(e: React.FormEvent) {
    e.preventDefault();
    setError("");
    setSuccess("");
    if (newPassword !== confirmPassword) {
      setError("Mật khẩu mới và xác nhận không khớp");
      return;
    }
    setLoading(true);
    try {
      await api.changePassword({
        old_password: oldPassword,
        new_password: newPassword,
        confirm_password: confirmPassword,
      });
      setSuccess("Đổi mật khẩu thành công. Đang chuyển về trang đăng nhập...");
      setTimeout(() => {
        logout();
        window.location.href = "/login";
      }, 1500);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Đổi mật khẩu thất bại");
    } finally {
      setLoading(false);
    }
  }

  if (!user) return null;

  return (
    <Dialog
      open={open}
      onOpenChange={(v) => {
        if (!v) resetForm();
        onOpenChange(v);
      }}
    >
      <DialogContent className="max-w-md">
        <DialogHeader>
          <DialogTitle>Thông tin tài khoản</DialogTitle>
          <DialogDescription>Thông tin cá nhân và đổi mật khẩu</DialogDescription>
        </DialogHeader>

        <div className="space-y-3 text-sm">
          <div className="flex justify-between">
            <span className="text-muted-foreground">Tên đăng nhập</span>
            <span className="font-medium">{user.username}</span>
          </div>
          <div className="flex justify-between">
            <span className="text-muted-foreground">Email</span>
            <span className="font-medium">{user.email}</span>
          </div>
          <div className="flex justify-between">
            <span className="text-muted-foreground">Vai trò</span>
            <Badge variant="secondary">{user.role}</Badge>
          </div>
          <div className="flex flex-wrap justify-end gap-1">
            {user.permissions.map((p) => (
              <Badge key={p} variant="outline" className="text-xs">
                {p}
              </Badge>
            ))}
          </div>
        </div>

        <Separator />

        <form onSubmit={handleChangePassword} className="space-y-3">
          <p className="text-sm font-medium">Đổi mật khẩu</p>
          <div className="space-y-2">
            <Label htmlFor="old-password">Mật khẩu cũ</Label>
            <Input
              id="old-password"
              type="password"
              autoComplete="current-password"
              value={oldPassword}
              onChange={(e) => setOldPassword(e.target.value)}
              required
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor="new-password">Mật khẩu mới</Label>
            <Input
              id="new-password"
              type="password"
              autoComplete="new-password"
              value={newPassword}
              onChange={(e) => setNewPassword(e.target.value)}
              required
              minLength={6}
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor="confirm-password">Xác nhận mật khẩu mới</Label>
            <Input
              id="confirm-password"
              type="password"
              autoComplete="new-password"
              value={confirmPassword}
              onChange={(e) => setConfirmPassword(e.target.value)}
              required
              minLength={6}
            />
          </div>
          {error && <p className="text-sm text-destructive">{error}</p>}
          {success && <p className="text-sm text-green-600">{success}</p>}
          <DialogFooter>
            <Button type="submit" disabled={loading}>
              {loading ? "Đang xử lý..." : "Đổi mật khẩu"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
