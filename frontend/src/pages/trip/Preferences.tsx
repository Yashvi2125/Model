import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Bot, Pencil, UserRound } from "lucide-react";
import { useState, type FormEvent } from "react";
import { Alert, Badge, Button, Input, PageLoader, QueryError, Select, Textarea } from "../../components/ui";
import { useToast } from "../../context/Toast";
import { useTrip } from "../../layouts/tripContext";
import { api, errorMessage, post, put } from "../../lib/api";
import { INTERESTS, interestLabel, money, shortDate } from "../../lib/format";
import type { MemberPreference, PreferenceInput, PreferencesOverview, Suggestion } from "../../lib/types";

const FIELD_LABELS: Record<string, string> = { destination: "Destination", trip_days: "Days", start_date: "From", end_date: "To", interests: "Interests",
  budget_min: "Budget from", budget_max: "Budget up to (per person)", accommodation: "Accommodation", dietary: "Diet", restrictions: "Restrictions", notes: "Notes" };
const MISSING: Record<string, string> = { interests: "interests", budget: "budget", dates: "travel dates", accommodation: "accommodation" };

function SourceTag({ p, field }: { p: MemberPreference; field: string }) {
  const s = p.sources[field];
  if (!s) return null;
  return s === "ai" ? <Badge tone="amber"><Bot className="h-3 w-3" />AI-suggested, you accepted</Badge> : <Badge><UserRound className="h-3 w-3" />Entered directly</Badge>;
}

function Row({ label, children, tag }: { label: string; children: React.ReactNode; tag?: React.ReactNode }) {
  return <div className="grid gap-1 py-2.5 sm:grid-cols-[9.5rem_1fr]"><dt className="text-sm text-ink-500">{label}</dt><dd className="flex flex-wrap items-center gap-2 text-[15px]">{children}{tag}</dd></div>;
}
const none = <span className="text-ink-400">Not shared yet</span>;

function MemberCard({ p, currency, onEdit }: { p: MemberPreference; currency: string; onEdit?: () => void }) {
  return (
    <article className="card p-5">
      <header className="flex items-center justify-between gap-3">
        <h3 className="text-lg font-semibold">{p.is_me ? `${p.user_name} (you)` : p.user_name}</h3>
        {onEdit && <Button variant="secondary" className="!py-1.5" onClick={onEdit}><Pencil className="h-4 w-4" />Edit my preferences</Button>}
      </header>
      {p.missing.length > 0 && <p className="mt-2 text-sm text-sun-700">Still missing: {p.missing.map((m) => MISSING[m]).join(", ")}</p>}
      <dl className="mt-2 divide-y divide-sand-200">
        <Row label="Destination" tag={<SourceTag p={p} field="destination" />}>{p.destination ?? none}</Row>
        <Row label="Activities" tag={<SourceTag p={p} field="interests" />}>{p.interests.length ? p.interests.map(interestLabel).join(", ") : none}</Row>
        <Row label="Budget (per person)" tag={<SourceTag p={p} field="budget_max" />}>{p.budget_min !== null || p.budget_max !== null ? `${p.budget_min !== null ? money(p.budget_min, currency) + " – " : "up to "}${p.budget_max !== null ? money(p.budget_max, currency) : "?"}` : none}</Row>
        <Row label="Travel dates" tag={<SourceTag p={p} field="start_date" />}>{p.start_date && p.end_date ? `${shortDate(p.start_date)} – ${shortDate(p.end_date)}` : p.trip_days ? `${p.trip_days} days` : none}</Row>
        <Row label="Accommodation" tag={<SourceTag p={p} field="accommodation" />}>{p.accommodation ?? none}</Row>
        <Row label="Dietary needs" tag={<SourceTag p={p} field="dietary" />}>{p.dietary ?? none}</Row>
        <Row label="Restrictions" tag={<SourceTag p={p} field="restrictions" />}>{p.restrictions ?? none}</Row>
        {p.notes && <Row label="Other notes" tag={<SourceTag p={p} field="notes" />}>{p.notes}</Row>}
      </dl>
    </article>
  );
}

function SuggestionCard({ s, tripId, currency }: { s: Suggestion; tripId: number; currency: string }) {
  const qc = useQueryClient(); const toast = useToast();
  const done = (data: PreferencesOverview) => qc.setQueryData(["prefs", tripId], data);
  const accept = useMutation({ mutationFn: () => post<PreferencesOverview>(`/api/trips/${tripId}/preferences/suggestions/${s.id}/accept`), onSuccess: (d) => { done(d); toast.success("Added to your preferences."); }, onError: (e) => toast.error(errorMessage(e)) });
  const dismiss = useMutation({ mutationFn: () => post<PreferencesOverview>(`/api/trips/${tripId}/preferences/suggestions/${s.id}/dismiss`), onSuccess: done, onError: (e) => toast.error(errorMessage(e)) });
  const provider = typeof (s.data as any)?._provider === "string" ? String((s.data as any)._provider) : null;
  return (
    <li className="rounded-xl border border-sun-500/40 bg-sun-100/50 p-4">
      <div className="flex items-center justify-between">
        <p className="text-sm font-semibold text-sun-700"><Bot className="mr-1 inline h-4 w-4" />Noticed in your chat — please check</p>
        {provider ? (
          <span className="inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium bg-sun-200 text-sun-800">
            {provider === "qwen" ? "Qwen 2.5 (Local)" : "Gemini"}
          </span>
        ) : null}
      </div>
      <ul className="mt-2 space-y-0.5 text-[15px]">
        {Object.entries(s.data)
          .filter(([k]) => !k.startsWith("_"))
          .map(([k, v]) => <li key={k}><span className="text-ink-500">{FIELD_LABELS[k] ?? k}: </span>
          {Array.isArray(v) ? v.map((x) => interestLabel(String(x))).join(", ") : k === "budget_max" ? money(Number(v), currency) : String(v)}</li>)}
      </ul>
      <div className="mt-3 flex gap-2"><Button className="!py-1.5" loading={accept.isPending} onClick={() => accept.mutate()}>Add to my preferences</Button>
        <Button variant="secondary" className="!py-1.5" loading={dismiss.isPending} onClick={() => dismiss.mutate()}>Dismiss</Button></div>
    </li>
  );
}

function EditForm({ me, tripId, currency, onClose }: { me: MemberPreference; tripId: number; currency: string; onClose: () => void }) {
  const qc = useQueryClient(); const toast = useToast();
  const [f, setF] = useState({ destination: me.destination ?? "", start: me.start_date ?? "", end: me.end_date ?? "", days: me.trip_days?.toString() ?? "",
    interests: me.interests, other: me.interests.filter((i) => !INTERESTS.some((x) => x.id === i)).join(", "), bmin: me.budget_min?.toString() ?? "", bmax: me.budget_max?.toString() ?? "",
    accommodation: me.accommodation ?? "", dietary: me.dietary ?? "", restrictions: me.restrictions ?? "", notes: me.notes ?? "" });
  const [err, setErr] = useState("");
  const set = (k: keyof typeof f, v: string | string[]) => setF((s) => ({ ...s, [k]: v }));
  const m = useMutation({
    mutationFn: (b: PreferenceInput) => put<PreferencesOverview>(`/api/trips/${tripId}/preferences/me`, b),
    onSuccess: (d) => { qc.setQueryData(["prefs", tripId], d); toast.success("Preferences saved."); onClose(); },
    onError: (e) => setErr(errorMessage(e)),
  });
  const submit = (e: FormEvent) => {
    e.preventDefault();
    const n = (s: string) => (s.trim() === "" ? null : Number(s));
    const t = (s: string) => (s.trim() === "" ? null : s.trim());
    const base = f.interests.filter((i) => INTERESTS.some((x) => x.id === i));
    const other = f.other.split(",").map((s) => s.trim()).filter(Boolean);
    setErr("");
    m.mutate({ destination: t(f.destination), start_date: t(f.start), end_date: t(f.end), trip_days: n(f.days), interests: [...base, ...other],
      budget_min: n(f.bmin), budget_max: n(f.bmax), accommodation: t(f.accommodation), dietary: t(f.dietary), restrictions: t(f.restrictions), notes: t(f.notes) });
  };
  return (
    <form onSubmit={submit} className="card space-y-4 p-5" noValidate>
      <h3 className="text-lg font-semibold">Edit my preferences</h3>
      <p className="-mt-2 text-sm text-ink-500">Anything you save here is marked as entered directly by you, and is never overwritten by the AI.</p>
      {err && <Alert>{err}</Alert>}
      <Input label="Destination" value={f.destination} onChange={(e) => set("destination", e.target.value)} optional />
      <div className="grid gap-4 sm:grid-cols-3">
        <Input label="Available from" type="date" value={f.start} onChange={(e) => set("start", e.target.value)} optional />
        <Input label="Available until" type="date" value={f.end} onChange={(e) => set("end", e.target.value)} optional />
        <Input label="Preferred trip length (days)" type="number" min={1} max={60} value={f.days} onChange={(e) => set("days", e.target.value)} optional />
      </div>
      <fieldset><legend className="mb-2 text-sm font-semibold">Activities you enjoy</legend>
        <div className="flex flex-wrap gap-2">{INTERESTS.map((i) => <button type="button" key={i.id} className="chip" aria-pressed={f.interests.includes(i.id)}
          onClick={() => set("interests", f.interests.includes(i.id) ? f.interests.filter((x) => x !== i.id) : [...f.interests, i.id])}>{i.label}</button>)}</div></fieldset>
      <Input label="Other interests" value={f.other} onChange={(e) => set("other", e.target.value)} hint="Separate with commas." optional />
      <div className="grid gap-4 sm:grid-cols-2">
        <Input label={`Budget from (${currency}, per person)`} type="number" min={0} value={f.bmin} onChange={(e) => set("bmin", e.target.value)} optional />
        <Input label={`Budget up to (${currency}, per person)`} type="number" min={0} value={f.bmax} onChange={(e) => set("bmax", e.target.value)} optional />
      </div>
      <Select label="Accommodation" value={["", "Budget hostel/homestay", "Mid-range hotel", "Premium hotel/resort"].includes(f.accommodation) ? f.accommodation : "__custom"} onChange={(e) => set("accommodation", e.target.value === "__custom" ? f.accommodation : e.target.value)} optional>
        <option value="">No preference yet</option><option>Budget hostel/homestay</option><option>Mid-range hotel</option><option>Premium hotel/resort</option><option value="__custom">Other (describe below)</option></Select>
      <Input label="Accommodation details" value={f.accommodation} onChange={(e) => set("accommodation", e.target.value)} optional />
      <Input label="Dietary needs" value={f.dietary} onChange={(e) => set("dietary", e.target.value)} optional />
      <Input label="Restrictions (health, mobility, constraints)" value={f.restrictions} onChange={(e) => set("restrictions", e.target.value)} optional />
      <Textarea label="Anything else" value={f.notes} onChange={(e) => set("notes", e.target.value)} optional />
      <div className="flex gap-2"><Button type="submit" loading={m.isPending}>Save preferences</Button><Button variant="secondary" onClick={onClose} disabled={m.isPending}>Cancel</Button></div>
    </form>
  );
}

export default function Preferences() {
  const { trip } = useTrip();
  const q = useQuery({ queryKey: ["prefs", trip.id], queryFn: () => api<PreferencesOverview>(`/api/trips/${trip.id}/preferences`) });
  const [editing, setEditing] = useState(false);
  if (q.isLoading) return <PageLoader />;
  if (q.error || !q.data) return <QueryError error={q.error} retry={() => q.refetch()} />;
  const me = q.data.members.find((m) => m.is_me)!;
  return (
    <div className="space-y-5">
      <div><h2 className="text-2xl font-bold sm:text-3xl">Trip preferences</h2><p className="text-ink-500">What each member wants. Update yours any time — the AI only suggests, you decide.</p></div>
      {q.data.trip_missing.includes("destination") && <Alert kind="warning">No destination has been chosen yet. Add one in your preferences or in chat so an itinerary can be planned.</Alert>}
      {q.data.my_suggestions.length > 0 && (
        <section aria-label="AI suggestions"><h3 className="mb-2 font-semibold">Suggestions from the AI for you</h3>
          <ul className="space-y-3">{q.data.my_suggestions.map((s) => <SuggestionCard key={s.id} s={s} tripId={trip.id} currency={trip.currency} />)}</ul></section>)}
      {editing ? <EditForm me={me} tripId={trip.id} currency={trip.currency} onClose={() => setEditing(false)} /> : null}
      <div className="grid gap-4 lg:grid-cols-2">
        {q.data.members.filter((m) => !(editing && m.is_me)).map((m) => <MemberCard key={m.user_id} p={m} currency={trip.currency} onEdit={m.is_me ? () => setEditing(true) : undefined} />)}
      </div>
    </div>
  );
}
