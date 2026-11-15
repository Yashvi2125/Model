export function money(amount: number | null | undefined, currency = "INR"): string {
  if (amount === null || amount === undefined) return "—";
  try {
    return new Intl.NumberFormat(currency === "INR" ? "en-IN" : "en-US", {
      style: "currency", currency, maximumFractionDigits: amount % 1 === 0 ? 0 : 2,
    }).format(amount);
  } catch {
    return `${currency} ${amount.toLocaleString()}`;
  }
}

const parse = (iso: string) => new Date(iso.length === 10 ? `${iso}T00:00:00` : iso);

export function dateRange(start: string, end: string): string {
  const s = parse(start), e = parse(end);
  const opts: Intl.DateTimeFormatOptions = { day: "numeric", month: "short" };
  const sameYear = s.getFullYear() === e.getFullYear();
  return `${s.toLocaleDateString("en-IN", sameYear ? opts : { ...opts, year: "numeric" })} – ${e.toLocaleDateString("en-IN", { ...opts, year: "numeric" })}`;
}

export const dayCount = (start: string, end: string) =>
  Math.round((parse(end).getTime() - parse(start).getTime()) / 86_400_000) + 1;

export const shortDate = (iso: string) => parse(iso).toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric" });

export const timeOf = (iso: string) => new Date(iso).toLocaleTimeString("en-IN", { hour: "numeric", minute: "2-digit" });

export function dayLabel(iso: string): string {
  const d = new Date(iso), now = new Date();
  const same = (a: Date, b: Date) => a.toDateString() === b.toDateString();
  const y = new Date(now); y.setDate(now.getDate() - 1);
  if (same(d, now)) return "Today";
  if (same(d, y)) return "Yesterday";
  return d.toLocaleDateString("en-IN", { weekday: "short", day: "numeric", month: "short" });
}

export const initials = (name: string) =>
  name.split(/\s+/).filter(Boolean).slice(0, 2).map((p) => p[0]!.toUpperCase()).join("");

export const todayISO = () => {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
};

export const INTERESTS: { id: string; label: string }[] = [
  { id: "adventure", label: "Adventure" }, { id: "nature", label: "Nature" }, { id: "beaches", label: "Beaches" },
  { id: "food", label: "Food" }, { id: "culture", label: "Culture & heritage" }, { id: "shopping", label: "Shopping" },
  { id: "relaxation", label: "Relaxation" }, { id: "nightlife", label: "Nightlife" }, { id: "spiritual", label: "Religious & spiritual sites" },
];
export const interestLabel = (id: string) => INTERESTS.find((i) => i.id === id)?.label ?? id;

export const CURRENCIES = ["INR", "USD", "EUR", "GBP", "AED", "SGD", "THB", "JPY"];
