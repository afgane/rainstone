import { ApiError, get, type SpendGuard } from "./api";

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
