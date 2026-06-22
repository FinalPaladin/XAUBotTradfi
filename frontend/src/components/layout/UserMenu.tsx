import { useEffect, useRef, useState } from "react";
import { ChevronDown, LogOut, UserCircle } from "lucide-react";
import { Button } from "@/components/ui/button";
import { useAuth } from "@/contexts/AuthContext";
import { AccountInfoModal } from "./AccountInfoModal";
import { cn } from "@/lib/utils";

export function UserMenu() {
  const { user, logout } = useAuth();
  const [open, setOpen] = useState(false);
  const [accountOpen, setAccountOpen] = useState(false);
  const menuRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    function handleClickOutside(e: MouseEvent) {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    }
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, []);

  if (!user) return null;

  const initials = user.username.slice(0, 2).toUpperCase();

  return (
    <>
      <div className="relative" ref={menuRef}>
        <Button
          variant="ghost"
          className="flex items-center gap-2 px-2"
          onClick={() => setOpen((v) => !v)}
        >
          <span className="flex h-8 w-8 items-center justify-center rounded-full bg-primary/10 text-sm font-semibold text-primary">
            {initials}
          </span>
          <span className="hidden text-sm font-medium sm:inline">{user.username}</span>
          <ChevronDown className={cn("h-4 w-4 transition-transform", open && "rotate-180")} />
        </Button>
        {open && (
          <div className="absolute right-0 z-50 mt-1 w-52 rounded-md border bg-card py-1 shadow-lg">
            <button
              type="button"
              className="flex w-full items-center gap-2 px-3 py-2 text-sm hover:bg-accent"
              onClick={() => {
                setOpen(false);
                setAccountOpen(true);
              }}
            >
              <UserCircle className="h-4 w-4" />
              Thông tin tài khoản
            </button>
            <button
              type="button"
              className="flex w-full items-center gap-2 px-3 py-2 text-sm text-destructive hover:bg-accent"
              onClick={() => {
                setOpen(false);
                logout();
                window.location.href = "/login";
              }}
            >
              <LogOut className="h-4 w-4" />
              Đăng xuất
            </button>
          </div>
        )}
      </div>
      <AccountInfoModal open={accountOpen} onOpenChange={setAccountOpen} />
    </>
  );
}
