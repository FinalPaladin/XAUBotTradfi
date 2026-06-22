import { useCallback, useEffect, useState } from "react";
import { Pencil, Plus, Users } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Checkbox } from "@/components/ui/checkbox";
import { api } from "@/lib/api";
import { ALL_PERMISSIONS, type User } from "@/lib/types";

type FormMode = "create" | "edit";

interface UserFormState {
  username: string;
  email: string;
  password: string;
  role: string;
  permissions: string[];
  is_active: boolean;
}

const emptyForm = (): UserFormState => ({
  username: "",
  email: "",
  password: "",
  role: "User",
  permissions: ["read:trades"],
  is_active: true,
});

export function AdminUsersPage() {
  const [users, setUsers] = useState<User[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [modalOpen, setModalOpen] = useState(false);
  const [mode, setMode] = useState<FormMode>("create");
  const [editingId, setEditingId] = useState<number | null>(null);
  const [form, setForm] = useState<UserFormState>(emptyForm);
  const [saving, setSaving] = useState(false);

  const loadUsers = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const data = await api.listUsers();
      setUsers(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Không tải được danh sách");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadUsers();
  }, [loadUsers]);

  function openCreate() {
    setMode("create");
    setEditingId(null);
    setForm(emptyForm());
    setModalOpen(true);
  }

  function openEdit(user: User) {
    setMode("edit");
    setEditingId(user.id);
    setForm({
      username: user.username,
      email: user.email,
      password: "",
      role: user.role,
      permissions: [...user.permissions],
      is_active: user.is_active,
    });
    setModalOpen(true);
  }

  function togglePermission(permId: string) {
    setForm((f) => ({
      ...f,
      permissions: f.permissions.includes(permId)
        ? f.permissions.filter((p) => p !== permId)
        : [...f.permissions, permId],
    }));
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setSaving(true);
    setError("");
    try {
      if (mode === "create") {
        await api.createUser({
          username: form.username.trim(),
          email: form.email.trim(),
          password: form.password,
          role: form.role,
          permissions: form.permissions,
          is_active: form.is_active,
        });
      } else if (editingId != null) {
        await api.updateUser(editingId, {
          email: form.email.trim(),
          password: form.password || undefined,
          role: form.role,
          permissions: form.permissions,
          is_active: form.is_active,
        });
      }
      setModalOpen(false);
      await loadUsers();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Lưu thất bại");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-2xl font-semibold tracking-tight">Quản lý tài khoản</h2>
          <p className="text-sm text-muted-foreground">
            Chỉ Admin — thêm, sửa và phân quyền người dùng
          </p>
        </div>
        <Button onClick={openCreate}>
          <Plus className="h-4 w-4" />
          Thêm mới Account
        </Button>
      </div>

      {error && !modalOpen && (
        <p className="text-sm text-destructive">{error}</p>
      )}

      <div className="rounded-lg border">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Username</TableHead>
              <TableHead>Email</TableHead>
              <TableHead>Active</TableHead>
              <TableHead>Quyền</TableHead>
              <TableHead className="w-24">Thao tác</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {loading ? (
              <TableRow>
                <TableCell colSpan={5} className="text-center text-muted-foreground">
                  Đang tải...
                </TableCell>
              </TableRow>
            ) : users.length === 0 ? (
              <TableRow>
                <TableCell colSpan={5} className="text-center text-muted-foreground">
                  Chưa có tài khoản
                </TableCell>
              </TableRow>
            ) : (
              users.map((u) => (
                <TableRow key={u.id}>
                  <TableCell className="font-medium">{u.username}</TableCell>
                  <TableCell>{u.email}</TableCell>
                  <TableCell>
                    <Badge variant={u.is_active ? "default" : "secondary"}>
                      {u.is_active ? "Active" : "Inactive"}
                    </Badge>
                  </TableCell>
                  <TableCell>
                    <div className="flex flex-wrap gap-1">
                      {u.permissions.map((p) => (
                        <Badge key={p} variant="outline" className="text-xs">
                          {p}
                        </Badge>
                      ))}
                    </div>
                  </TableCell>
                  <TableCell>
                    <Button variant="ghost" size="icon" onClick={() => openEdit(u)}>
                      <Pencil className="h-4 w-4" />
                    </Button>
                  </TableCell>
                </TableRow>
              ))
            )}
          </TableBody>
        </Table>
      </div>

      <Dialog open={modalOpen} onOpenChange={setModalOpen}>
        <DialogContent className="max-w-lg max-h-[90vh] overflow-y-auto">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <Users className="h-5 w-5" />
              {mode === "create" ? "Thêm mới Account" : "Chỉnh sửa Account"}
            </DialogTitle>
          </DialogHeader>
          <form onSubmit={handleSubmit} className="space-y-4">
            {mode === "create" && (
              <div className="space-y-2">
                <Label htmlFor="username">Username</Label>
                <Input
                  id="username"
                  value={form.username}
                  onChange={(e) => setForm({ ...form, username: e.target.value })}
                  required
                />
              </div>
            )}
            <div className="space-y-2">
              <Label htmlFor="email">Email</Label>
              <Input
                id="email"
                type="email"
                value={form.email}
                onChange={(e) => setForm({ ...form, email: e.target.value })}
                required
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="password">
                {mode === "create" ? "Mật khẩu" : "Mật khẩu mới (để trống nếu không đổi)"}
              </Label>
              <Input
                id="password"
                type="password"
                value={form.password}
                onChange={(e) => setForm({ ...form, password: e.target.value })}
                required={mode === "create"}
                minLength={mode === "create" ? 6 : undefined}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="role">Vai trò</Label>
              <select
                id="role"
                className="flex h-9 w-full rounded-md border border-input bg-background px-3 text-sm"
                value={form.role}
                onChange={(e) => setForm({ ...form, role: e.target.value })}
              >
                <option value="User">User</option>
                <option value="Admin">Admin</option>
              </select>
            </div>
            <div className="flex items-center gap-2">
              <Checkbox
                id="is_active"
                checked={form.is_active}
                onChange={(e) => setForm({ ...form, is_active: e.target.checked })}
              />
              <Label htmlFor="is_active">Tài khoản Active</Label>
            </div>
            <div className="space-y-2">
              <Label>Phân quyền</Label>
              <div className="space-y-2 rounded-md border p-3">
                {ALL_PERMISSIONS.map(({ id, label }) => (
                  <label key={id} className="flex items-center gap-2 text-sm">
                    <Checkbox
                      checked={form.permissions.includes(id)}
                      onChange={() => togglePermission(id)}
                    />
                    <span>{label}</span>
                    <span className="text-muted-foreground">({id})</span>
                  </label>
                ))}
              </div>
            </div>
            {error && modalOpen && (
              <p className="text-sm text-destructive">{error}</p>
            )}
            <DialogFooter>
              <Button type="button" variant="outline" onClick={() => setModalOpen(false)}>
                Hủy
              </Button>
              <Button type="submit" disabled={saving}>
                {saving ? "Đang lưu..." : "Lưu"}
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>
    </div>
  );
}
