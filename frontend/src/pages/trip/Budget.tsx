import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Calculator, RefreshCw } from "lucide-react";
import { Link } from "react-router-dom";
import { Alert, Badge, Button, EmptyState, PageLoader, QueryError } from "../../components/ui";
import { useToast } from "../../context/Toast";
import { useTrip } from "../../layouts/tripContext";
import { api, errorMessage, post } from "../../lib/api";
import { money } from "../../lib/format";
import type { BudgetData } from "../../lib/types";

const CAT: Record<string, string> = { accommodation: "Accommodation", food: "Food", transport: "Transport", activities: "Activities & sightseeing", other: "Other" };
const BASIS: Record<string, string> = { group_total: "group total", per_person: "per person", per_person_per_day: "per person per day", per_night_group: "per night (whole group)" };

function Stat({ label, value, sub, tone }: { label: string; value: string; sub?: string; tone?: "good" | "bad" }) {
  return <div className="card card-hover relative overflow-hidden p-4 sm:p-5"><span className={`absolute inset-x-0 top-0 h-1 ${tone === "bad" ? "bg-coral-500" : tone === "good" ? "bg-lagoon-500" : "bg-sun-500"}`} aria-hidden /><p className="text-xs font-medium text-ink-500 sm:text-sm">{label}</p>
    <p className={`mt-1 break-words font-display text-xl font-bold sm:text-3xl ${tone === "bad" ? "text-coral-700" : tone === "good" ? "text-lagoon-700" : ""}`}>{value}</p>{sub && <p className="mt-1 text-[11px] leading-snug text-ink-500 sm:text-xs">{sub}</p>}</div>;
}

export default function Budget() {
  const { trip } = useTrip();
  const qc = useQueryClient(); const toast = useToast();
  const q = useQuery({ queryKey: ["budget", trip.id], queryFn: () => api<BudgetData>(`/api/trips/${trip.id}/budget`) });
  const re = useMutation({ mutationFn: () => post<BudgetData>(`/api/trips/${trip.id}/budget/estimate`), onSuccess: (d) => { qc.setQueryData(["budget", trip.id], d); toast.success("Budget recalculated."); }, onError: (e) => toast.error(errorMessage(e)) });
  if (q.isLoading) return <PageLoader />;
  if (q.error || !q.data) return <QueryError error={q.error} retry={() => q.refetch()} />;
  const b = q.data; const cur = b.currency;
  const over = b.within_budget === false;
  const pct = b.group_budget && b.total ? Math.min(100, (b.total / b.group_budget) * 100) : 0;

  return (
    <div className="space-y-4 sm:space-y-6">
      <div><h2 className="text-2xl font-bold sm:text-3xl">Budget</h2>
        <p className="text-ink-500">Costs come from the itinerary; every total and per-person split is calculated in code, not by the AI. These are <strong>estimates</strong>, not confirmed payments.</p></div>

      <div className="grid grid-cols-2 gap-3 sm:gap-4 lg:grid-cols-4">
        <Stat label="Group budget you set" value={money(b.group_budget, cur)} sub={b.per_person_budget !== null ? `${money(b.per_person_budget, cur)} per person · ${b.flexibility.replace("_", " ")}` : "Not set — add one when creating a trip"} />
        <Stat label="Estimated total" value={b.has_estimate ? money(b.total, cur) : "—"} sub={b.has_estimate ? `${b.travelers} travellers · ${b.days} days` : undefined} />
        <Stat label="Estimated per person" value={b.has_estimate ? money(b.per_person, cur) : "—"} sub={b.has_estimate ? "Equal split, rounded to the nearest paisa" : undefined} />
        <Stat label={over ? "Over budget by" : "Remaining"} value={b.difference !== null && b.has_estimate ? money(Math.abs(b.difference), cur) : "—"} tone={b.has_estimate && b.within_budget !== null ? (over ? "bad" : "good") : undefined}
          sub={b.within_budget === null ? (b.has_estimate ? "Set a group budget to compare" : undefined) : over ? "The plan exceeds your stated budget" : "The plan is within your stated budget"} />
      </div>

      {b.has_estimate && b.group_budget && b.total && b.total > b.group_budget * 2 && <Alert kind="warning">This estimate is more than double your budget. That can happen when a price in the plan is read as per-person instead of for the whole group (or the other way round). Check the cost lines below, then use <strong>Re-extract</strong> if something looks wrong.</Alert>}
      {b.generating && <Alert kind="info">An itinerary is being generated; this page will update when it’s done.</Alert>}

      {!b.has_estimate ? (
        <EmptyState icon={<Calculator className="h-7 w-7" />} title={b.itinerary_version ? "No costs to total yet" : "Generate an itinerary first"}
          text={b.itinerary_version ? (b.budget_error ?? "The itinerary doesn’t state costs we can total.") : "The budget is built from the costs stated in your itinerary. Until then there’s nothing to calculate, and we won’t guess."}
          action={b.itinerary_version ? <Button onClick={() => re.mutate()} loading={re.isPending}><RefreshCw className="h-4 w-4" />Try again</Button> : <Link className="btn-primary" to="../itinerary">Go to itinerary</Link>} />
      ) : (
        <>
          {b.group_budget && <div className="card p-5"><div className="flex justify-between text-sm"><span className="font-semibold">Estimate vs. your budget</span><span className="text-ink-500">{Math.round((b.total! / b.group_budget) * 100)}%</span></div>
            <div className="mt-3 h-3.5 overflow-hidden rounded-full bg-sand-200" role="progressbar" aria-valuenow={Math.round(pct)} aria-valuemin={0} aria-valuemax={100} aria-label="Estimate as a share of budget">
              <div className={`h-full rounded-full ${over ? "bg-coral-500" : "bg-gradient-to-r from-lagoon-500 to-lagoon-600"} transition-all duration-700`} style={{ width: `${pct}%` }} /></div></div>}
          <section className="card p-4 sm:p-5"><h3 className="text-lg font-semibold">Where the money goes</h3>
            <ul className="mt-4 space-y-4">{b.categories.map((c) => (
              <li key={c.category}><div className="flex flex-wrap items-baseline justify-between gap-2"><span className="font-medium">{CAT[c.category]}</span>
                <span className="text-sm"><strong>{money(c.total, cur)}</strong> <span className="text-ink-500">· {money(c.per_person, cur)} per person · {Math.round(c.share * 100)}%</span></span></div>
                <div className="mt-1.5 h-2 overflow-hidden rounded-full bg-sand-200"><div className="h-full rounded-full bg-lagoon-500" style={{ width: `${c.share * 100}%` }} /></div></li>))}</ul>
            <p className="mt-4 text-xs text-ink-500">Categories with no stated cost aren’t shown, so “unavailable” isn’t the same as zero.</p></section>
          <section className="card p-4 sm:p-5"><div className="flex flex-wrap items-center justify-between gap-2"><h3 className="text-lg font-semibold">Cost lines taken from the plan <Badge>Estimates</Badge></h3>
            <Button variant="ghost" className="!py-1.5" loading={re.isPending} onClick={() => re.mutate()}><RefreshCw className="h-4 w-4" />Re-extract</Button></div>
            <ul className="mt-3 space-y-2.5 sm:hidden">{b.items.map((i, k) => <li key={k} className="rounded-2xl bg-sand-50/80 p-3.5 ring-1 ring-sand-200/70"><div className="flex items-start justify-between gap-3"><div className="min-w-0"><p className="font-medium">{i.label || CAT[i.category]}</p><p className="text-xs text-ink-500">{CAT[i.category]}</p></div><p className="shrink-0 font-semibold">{money(i.line_total, cur)}</p></div><p className="mt-1.5 text-sm">{money(i.amount, cur)} {BASIS[i.basis]}</p>{i.source_text && <p className="mt-1 break-words text-xs text-ink-500">{i.source_text}</p>}</li>)}</ul>
            <div className="mt-3 hidden overflow-x-auto sm:block"><table className="w-full min-w-[34rem] text-left text-sm"><thead><tr className="border-b border-sand-200 text-ink-500"><th className="py-2 pr-3 font-medium">Item</th><th className="pr-3 font-medium">Stated as</th><th className="pr-3 font-medium">Group total</th><th className="font-medium">From the plan</th></tr></thead>
              <tbody>{b.items.map((i, k) => <tr key={k} className="border-b border-sand-100 align-top"><td className="py-2 pr-3"><span className="font-medium">{i.label || CAT[i.category]}</span><br /><span className="text-xs text-ink-500">{CAT[i.category]}</span></td>
                <td className="pr-3">{money(i.amount, cur)} {BASIS[i.basis]}</td><td className="pr-3 font-semibold">{money(i.line_total, cur)}</td><td className="text-ink-500">{i.source_text}</td></tr>)}</tbody></table></div>
            <p className="mt-3 text-xs text-ink-500">From itinerary v{b.itinerary_version}. Check the “From the plan” column — the AI extracts these lines, and you should verify them against real prices.</p></section>
        </>)}
    </div>
  );
}
