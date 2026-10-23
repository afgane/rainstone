import { ApiError, get, type SpendGuard } from "./api";

export function spendLimitPercent(guard: SpendGuard): number | null {
  if (guard.limit === null || guard.snapshot.amount === null || guard.source_changed) return null;
  const limit = Number(guard.limit);
  const amount = Number(guard.snapshot.amount);
  if (!Number.isFinite(limit) || !Number.isFinite(amount) || limit <= 0) return null;
  return Math.min(100, Math.max(0, amount / limit * 100));
}

/** Compare decimal strings exactly; this preview never replaces server validation. */
export function triggersImmediately(spend: string | null, margin: string, limit: string): boolean {
  if (spend === null) return false;
  const values = [spend, margin, limit].map(value => value.replace(/^0E[-+]\d+$/, "0").split("."));
  if (values.some(parts => !parts.every(part => /^\d+$/.test(part)))) return false;
  const scale = Math.max(...values.map(parts => (parts[1] || "").length));
  const [used, reserve, ceiling] = values.map(([whole, fraction = ""]) => BigInt(whole + fraction.padEnd(scale, "0")));
  return used + reserve >= ceiling;
}

export async function readGuard(signal?: AbortSignal): Promise<SpendGuard> {
  const guard = await get<SpendGuard>("/spend-guard", signal);
  if (typeof guard.revision !== "number" || !guard.snapshot) throw new ApiError("Batch limit status is unavailable", 503);
  return guard;
}

/** The server requires a ceiling strictly above spend, including sub-cent costs. */
export function minimumSpendLimit(spend: string | null): string {
  const [whole, fraction = ""] = (spend ?? "0").replace(/^0E[-+]\d+$/, "0").split(".");
  const cents = BigInt(whole) * 100n + BigInt(fraction.padEnd(2, "0").slice(0, 2)) + 1n;
  return `${cents / 100n}.${String(cents % 100n).padStart(2, "0")}`;
}
