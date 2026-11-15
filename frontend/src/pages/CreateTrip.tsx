import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Check } from "lucide-react";
import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { Alert, Button, Input, Select, Textarea } from "../components/ui";
import { useToast } from "../context/Toast";
import { errorMessage, post } from "../lib/api";
import { CURRENCIES, INTERESTS, dateRange, dayCount, interestLabel, money, todayISO } from "../lib/format";
import type { TripCreateInput, TripDetail } from "../lib/types";
import { validateTripStep, type TripDraft } from "../lib/validation";

const STEPS = ["Basics", "Budget", "Interests", "Needs", "Review"];
const FLEX = [["strict", "Strict", "We shouldn’t go over."], ["flexible", "Flexible", "A little over is okay."], ["very_flexible", "Very flexible", "Budget is a guide."]] as const;

export function draftToInput(d: TripDraft): TripCreateInput {
  const n = (s: string) => (s.trim() === "" ? null : Number(s));
  const t = (s: string) => (s.trim() === "" ? null : s.trim());
  const other = d.otherInterests.split(",").map((s) => s.trim()).filter(Boolean);
  return {
    name: d.name.trim(), destination: d.undecided ? null : t(d.destination), destination_undecided: d.undecided,
    start_date: d.start, end_date: d.end, travelers_count: Number(d.travelers), budget_total: n(d.total),
    budget_per_person: n(d.perPerson), currency: d.currency, budget_flexibility: d.flexibility,
    interests: [...d.interests, ...other], accommodation_pref: t(d.accommodation), dietary: t(d.dietary),
    accessibility: t(d.accessibility), constraints: t(d.constraints), notes: t(d.notes),
  };
}

export default function CreateTrip() {
  const today = todayISO();
  const [step, setStep] = useState(0);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [formError, setFormError] = useState("");
  const [d, setD] = useState<TripDraft>({ name: "", destination: "", undecided: false, start: "", end: "", travelers: "2", total: "", perPerson: "",
    currency: "INR", flexibility: "flexible", interests: [], otherInterests: "", accommodation: "", dietary: "", accessibility: "", constraints: "", notes: "" });
  const set = <K extends keyof TripDraft>(k: K, v: TripDraft[K]) => setD((s) => ({ ...s, [k]: v }));
  const navigate = useNavigate(); const qc = useQueryClient(); const toast = useToast();

  const create = useMutation({
    mutationFn: () => post<TripDetail>("/api/trips", draftToInput(d)),
    onSuccess: (t) => { qc.invalidateQueries({ queryKey: ["trips"] }); toast.success("Trip created. Invite your group with the trip code."); navigate(`/app/trips/${t.id}/members`); },
    onError: (e) => setFormError(errorMessage(e)),
  });

  const next = () => {
    const er = validateTripStep(step, d, today); setErrors(er);
    if (Object.keys(er).length === 0) setStep((s) => s + 1);
  };
  const submit = () => {
    for (const s of [0, 1]) { const er = validateTripStep(s, d, today); if (Object.keys(er).length) { setErrors(er); setStep(s); return; } }
    setFormError(""); create.mutate();
  };
  const input = draftToInput(d);

  return (
    <div className="mx-auto max-w-2xl">
      <h1 className="text-3xl font-bold">Create a Trip</h1>
      <ol className="mt-6 flex items-center gap-2" aria-label="Progress">
        {STEPS.map((s, i) => (
          <li key={s} className="flex flex-1 items-center gap-2" aria-current={i === step ? "step" : undefined}>
            <span className={`flex h-7 w-7 shrink-0 items-center justify-center rounded-full text-xs font-bold ${i < step ? "bg-lagoon-600 text-white" : i === step ? "bg-lagoon-50 text-lagoon-800 ring-2 ring-lagoon-600" : "bg-sand-200 text-ink-500"}`}>
              {i < step ? <Check className="h-4 w-4" /> : i + 1}</span>
            <span className={`hidden text-sm font-medium sm:block ${i === step ? "text-ink-900" : "text-ink-500"}`}>{s}</span>
            {i < STEPS.length - 1 && <span className="h-px flex-1 bg-sand-300" />}
          </li>))}
      </ol>

      <div className="card mt-6 space-y-5 p-6">
        {step === 0 && <>
          <h2 className="text-xl font-semibold">The basics</h2>
          <Input label="Trip name" value={d.name} onChange={(e) => set("name", e.target.value)} error={errors.name} placeholder="Goa with the college gang" />
          <div>
            <Input label="Destination" value={d.destination} disabled={d.undecided} onChange={(e) => set("destination", e.target.value)} error={errors.destination} placeholder="Udaipur" />
            <label className="mt-2 flex items-center gap-2 text-sm text-ink-700"><input type="checkbox" className="h-4 w-4 accent-lagoon-600" checked={d.undecided}
              onChange={(e) => set("undecided", e.target.checked)} />We haven’t decided yet — members can suggest places in the chat</label>
          </div>
          <div className="grid gap-4 sm:grid-cols-2">
            <Input label="Departure date" type="date" min={today} value={d.start} onChange={(e) => set("start", e.target.value)} error={errors.start} />
            <Input label="Return date" type="date" min={d.start || today} value={d.end} onChange={(e) => set("end", e.target.value)} error={errors.end} />
          </div>
          <Input label="Number of travellers" type="number" min={1} max={50} value={d.travelers} onChange={(e) => set("travelers", e.target.value)} error={errors.travelers} hint="Everyone going, including people who won’t use the app." />
        </>}

        {step === 1 && <>
          <h2 className="text-xl font-semibold">Budget</h2>
          <p className="-mt-3 text-sm text-ink-500">Rough numbers are fine; both fields are optional and can be refined later.</p>
          <Select label="Currency" value={d.currency} onChange={(e) => set("currency", e.target.value)}>{CURRENCIES.map((c) => <option key={c}>{c}</option>)}</Select>
          <div className="grid gap-4 sm:grid-cols-2">
            <Input label="Total group budget" type="number" min={0} inputMode="decimal" value={d.total} onChange={(e) => set("total", e.target.value)} error={errors.total} optional />
            <Input label="Preferred budget per person" type="number" min={0} inputMode="decimal" value={d.perPerson} onChange={(e) => set("perPerson", e.target.value)} error={errors.perPerson} optional />
          </div>
          <fieldset><legend className="mb-2 text-sm font-semibold">How flexible is the budget?</legend>
            <div className="grid gap-2 sm:grid-cols-3">{FLEX.map(([v, l, h]) => (
              <label key={v} className={`cursor-pointer rounded-xl border p-3 text-sm ${d.flexibility === v ? "border-lagoon-600 bg-lagoon-50" : "border-sand-300 bg-white hover:bg-sand-100"} focus-within:ring-2 focus-within:ring-lagoon-600`}>
                <input type="radio" name="flex" className="sr-only" checked={d.flexibility === v} onChange={() => set("flexibility", v)} />
                <span className="block font-semibold">{l}</span><span className="text-ink-500">{h}</span></label>))}</div></fieldset>
        </>}

        {step === 2 && <>
          <h2 className="text-xl font-semibold">What does your group enjoy?</h2>
          <p className="-mt-3 text-sm text-ink-500">Pick as many as you like. Other members add their own after joining.</p>
          <div className="flex flex-wrap gap-2" role="group" aria-label="Interests">{INTERESTS.map((i) => (
            <button key={i.id} type="button" className="chip" aria-pressed={d.interests.includes(i.id)}
              onClick={() => set("interests", d.interests.includes(i.id) ? d.interests.filter((x) => x !== i.id) : [...d.interests, i.id])}>{i.label}</button>))}</div>
          <Input label="Other interests" value={d.otherInterests} onChange={(e) => set("otherInterests", e.target.value)} placeholder="photography, street food, live music" hint="Separate with commas." optional />
        </>}

        {step === 3 && <>
          <h2 className="text-xl font-semibold">Anything we should know?</h2>
          <Input label="Accommodation preferences" value={d.accommodation} onChange={(e) => set("accommodation", e.target.value)} placeholder="Homestay or mid-range hotel, shared rooms are fine" optional />
          <Input label="Dietary restrictions" value={d.dietary} onChange={(e) => set("dietary", e.target.value)} placeholder="2 vegetarians, 1 Jain" optional />
          <Input label="Accessibility requirements" value={d.accessibility} onChange={(e) => set("accessibility", e.target.value)} placeholder="Step-free access for a grandparent" optional />
          <Input label="Travel constraints" value={d.constraints} onChange={(e) => set("constraints", e.target.value)} placeholder="No overnight travel; must be back by Sunday" optional />
          <Textarea label="Additional notes" value={d.notes} onChange={(e) => set("notes", e.target.value)} optional />
        </>}

        {step === 4 && <>
          <h2 className="text-xl font-semibold">Review your trip</h2>
          <dl className="divide-y divide-sand-200 text-sm">
            {([
              ["Trip", input.name], ["Destination", input.destination ?? "Undecided"],
              ["Dates", input.start_date && input.end_date ? `${dateRange(input.start_date, input.end_date)} (${dayCount(input.start_date, input.end_date)} days)` : "—"],
              ["Travellers", String(input.travelers_count)],
              ["Group budget", input.budget_total !== null ? money(input.budget_total, input.currency) : "Not set"],
              ["Per person", input.budget_per_person !== null ? money(input.budget_per_person, input.currency) : "Not set"],
              ["Flexibility", FLEX.find((f) => f[0] === input.budget_flexibility)![1]],
              ["Interests", input.interests.length ? input.interests.map(interestLabel).join(", ") : "None yet"],
              ["Accommodation", input.accommodation_pref ?? "—"], ["Dietary", input.dietary ?? "—"],
              ["Accessibility", input.accessibility ?? "—"], ["Constraints", input.constraints ?? "—"], ["Notes", input.notes ?? "—"],
            ] as [string, string][]).map(([k, v]) => <div key={k} className="grid grid-cols-[8rem_1fr] gap-3 py-2"><dt className="text-ink-500">{k}</dt><dd className="break-words font-medium">{v}</dd></div>)}
          </dl>
          {formError && <Alert>{formError}</Alert>}
        </>}

        <div className="flex justify-between gap-3 border-t border-sand-200 pt-5">
          <Button variant="secondary" onClick={() => { setErrors({}); setStep((s) => s - 1); }} disabled={step === 0 || create.isPending}>Back</Button>
          {step < STEPS.length - 1 ? <Button onClick={next}>Next</Button> : <Button onClick={submit} loading={create.isPending}>{create.isPending ? "Creating…" : "Create Trip"}</Button>}
        </div>
      </div>
    </div>
  );
}
