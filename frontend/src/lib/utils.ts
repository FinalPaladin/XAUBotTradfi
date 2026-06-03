import { type ClassValue, clsx } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

export function formatMoney(value: number, currency = "USD") {
  return new Intl.NumberFormat("vi-VN", {
    style: "currency",
    currency,
    maximumFractionDigits: 2,
  }).format(value);
}

export function formatNumber(value: number, digits = 2) {
  return new Intl.NumberFormat("vi-VN", {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  }).format(value);
}

export function formatDateTime(iso: string) {
  return new Intl.DateTimeFormat("vi-VN", {
    dateStyle: "short",
    timeStyle: "medium",
  }).format(new Date(iso));
}

export function sideLabel(side: string) {
  if (side === "BUY") return "Long";
  if (side === "SELL") return "Short";
  return side;
}
