export const passwordChecks = (pw: string) => [
  { id: "len", label: "At least 8 characters", ok: pw.length >= 8 },
  { id: "letter", label: "One letter", ok: /[A-Za-z]/.test(pw) },
  { id: "num", label: "One number", ok: /\d/.test(pw) },
];
export const passwordValid = (pw: string) => passwordChecks(pw).every((c) => c.ok);
export const emailValid = (e: string) => /^[^\s@]+@[^\s@]+\.[^\s@]{2,}$/.test(e.trim());

export interface TripDraft {
  name: string; destination: string; undecided: boolean; start: string; end: string; travelers: string;
  total: string; perPerson: string; currency: string; flexibility: "strict" | "flexible" | "very_flexible";
  interests: string[]; otherInterests: string; accommodation: string; dietary: string; accessibility: string;
  constraints: string; notes: string;
}

export function validateTripStep(step: number, d: TripDraft, today: string): Record<string, string> {
  const e: Record<string, string> = {};
  if (step === 0) {
    if (d.name.trim().length < 2) e.name = "Give your trip a name (at least 2 characters).";
    if (!d.undecided && !d.destination.trim()) e.destination = "Enter a destination, or tick “We haven’t decided yet”.";
    if (!d.start) e.start = "Choose a departure date.";
    else if (d.start < today) e.start = "Departure can’t be in the past.";
    if (!d.end) e.end = "Choose a return date.";
    else if (d.start && d.end < d.start) e.end = "Return date can’t be before departure.";
    else if (d.start && d.end && (new Date(d.end).getTime() - new Date(d.start).getTime()) / 864e5 > 60) e.end = "Trips longer than 60 days aren’t supported.";
    const n = Number(d.travelers);
    if (!Number.isInteger(n) || n < 1 || n > 50) e.travelers = "Enter a whole number between 1 and 50.";
  }
  if (step === 1) {
    for (const k of ["total", "perPerson"] as const) {
      if (d[k].trim() !== "" && (!(Number(d[k]) >= 0) || Number.isNaN(Number(d[k])))) e[k] = "Enter a valid amount.";
    }
  }
  return e;
}
