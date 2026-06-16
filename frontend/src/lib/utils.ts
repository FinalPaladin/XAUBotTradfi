import { type ClassValue, clsx } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

export function formatLogNumber(value: number, digits = 2) {
  return new Intl.NumberFormat("en-US", {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  }).format(value);
}

/** Parse API datetime — mọi timestamp backend lưu theo UTC (kể cả naive ISO). */
export function parseServerDateTime(iso: string) {
  const trimmed = iso.trim();
  const hasTz = /[Zz]$|[+-]\d{2}:\d{2}$/.test(trimmed);
  if (hasTz) {
    return new Date(trimmed);
  }
  // Naive ISO từ API = UTC wall-clock (MySQL/MT5), không phải giờ local.
  return new Date(`${trimmed}Z`);
}

export function formatLogDateTime(iso: string) {
  const d = parseServerDateTime(iso);
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`;
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
