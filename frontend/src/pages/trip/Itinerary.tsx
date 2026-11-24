import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CalendarDays, Download, FileText, Map as MapIcon, MessageSquare, Moon, Printer, RefreshCw, Sparkles, Sun, Sunrise, Users, Wallet } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router-dom";
import { Markdown } from "../../components/Markdown";
import { Alert, Badge, Button, EmptyState, PageLoader, QueryError, Spinner, Textarea } from "../../components/ui";
import { useToast } from "../../context/Toast";
import { useTrip } from "../../layouts/tripContext";
import { api, errorMessage, post } from "../../lib/api";
import { dateRange, dayCount, money } from "../../lib/format";
import type { BudgetData, Itinerary } from "../../lib/types";

const PERIODS = { morning: { label: "Morning", icon: Sunrise }, afternoon: { label: "Afternoon", icon: Sun }, evening: { label: "Evening", icon: Moon } } as const;

function GenerateBox({ onGenerate, busy, label }: { onGenerate: (i: string) => void; busy: boolean; label: string }) {
  const [instr, setInstr] = useState("");
  return (
    <div className="space-y-3">
      <Textarea label="Anything the planner should focus on?" value={instr} onChange={(e) => setInstr(e.target.value)} maxLength={1000} optional
        placeholder="More street food, a slow morning on day 2, skip long drives…" hint="The planner also uses everyone’s saved preferences and any compromises you agreed." />
      <Button onClick={() => onGenerate(instr)} loading={busy}><Sparkles className="h-4 w-4" />{label}</Button>
    </div>
  );
}

function download(it: Itinerary, name: string) {
  const blob = new Blob([`# ${name} — itinerary v${it.version}\n\n${it.plan_markdown ?? ""}\n\n${it.research_markdown ? "## Researcher notes\n\n" + it.research_markdown : ""}\n`], { type: "text/markdown" });
  const a = document.createElement("a"); a.href = URL.createObjectURL(blob); a.download = `${name.replace(/\W+/g, "-").toLowerCase()}-itinerary-v${it.version}.md`; a.click(); URL.revokeObjectURL(a.href);
}

export default function ItineraryPage() {
  const { trip } = useTrip();
  const qc = useQueryClient(); const toast = useToast();
  const [showRaw, setShowRaw] = useState(false); const [regen, setRegen] = useState(false);
  const [swappingDay, setSwappingDay] = useState<number | null>(null);
  const [swapInstruction, setSwapInstruction] = useState("");
  const q = useQuery({ queryKey: ["itinerary", trip.id], queryFn: () => api<Itinerary | null>(`/api/trips/${trip.id}/itinerary`),
    refetchInterval: (query) => (query.state.data?.status === "running" ? 4000 : false) });
  const budget = useQuery({ queryKey: ["budget", trip.id], queryFn: () => api<BudgetData>(`/api/trips/${trip.id}/budget`), enabled: q.data?.status === "succeeded" });
  const gen = useMutation({
    mutationFn: (instructions: string) => post<Itinerary>(`/api/trips/${trip.id}/itinerary/generate`, { instructions }),
    onSuccess: (it) => { qc.setQueryData(["itinerary", trip.id], it); setRegen(false); toast.success("Planning started. This can take a minute or two."); },
    onError: (e) => toast.error(errorMessage(e)),
  });
  const swapMutation = useMutation({
    mutationFn: ({ day, instruction }: { day: number; instruction: string }) =>
      post<Itinerary>(`/api/trips/${trip.id}/itinerary/days/${day}/swap`, { instruction }),
    onSuccess: (it) => {
      qc.setQueryData(["itinerary", trip.id], it);
      setSwappingDay(null);
      setSwapInstruction("");
      toast.success("Day updated successfully!");
    },
    onError: (e) => toast.error(errorMessage(e)),
  });
  const it = q.data;

  if (q.isLoading) return <PageLoader />;
  if (q.error) return <QueryError error={q.error} retry={() => q.refetch()} />;

  if (!it) return (
    <div className="mx-auto max-w-xl">
      <EmptyState icon={<Sparkles className="h-7 w-7" />} title="No itinerary yet" text="The Planner and Researcher agents will draft a day-by-day plan from your group’s preferences. Review preferences first for the best result."
        action={<div className="w-full text-left"><GenerateBox onGenerate={(i) => gen.mutate(i)} busy={gen.isPending} label="Generate itinerary" /></div>} />
    </div>);

  if (it.status === "running") return (
    <div className="card mx-auto max-w-xl p-8 text-center" role="status">
      <Spinner className="mx-auto h-8 w-8 text-lagoon-600" /><h2 className="mt-4 text-xl font-semibold">Planning your itinerary…</h2>
      <p className="mt-1 text-ink-500">The Planner is drafting and the Researcher is checking it. This usually takes one to two minutes. You can keep chatting — this page updates by itself.</p>
    </div>);

  if (it.status === "failed") return (
    <div className="mx-auto max-w-xl space-y-4">
      <Alert action={undefined}>Version {it.version} couldn’t be generated: {it.error}</Alert>
      <div className="card p-6"><GenerateBox onGenerate={(i) => gen.mutate(i)} busy={gen.isPending} label="Try again" /></div>
      {it.version > 1 && <Link to="" className="text-sm underline" onClick={() => qc.invalidateQueries({ queryKey: ["itinerary", trip.id] })}>Refresh</Link>}
    </div>);

  const d = it.days; const b = budget.data;
  return (
    <div className="space-y-6">
      <section className="card p-6">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div><h2 className="text-2xl font-bold">{trip.destination ?? "Your itinerary"}</h2>
            <p className="mt-1 flex flex-wrap items-center gap-x-5 gap-y-1 text-sm text-ink-500">
              <span className="inline-flex items-center gap-1.5"><CalendarDays className="h-4 w-4" />{dateRange(trip.start_date, trip.end_date)} · {dayCount(trip.start_date, trip.end_date)} days</span>
              <span className="inline-flex items-center gap-1.5"><Users className="h-4 w-4" />{trip.travelers_count} travellers</span>
              <span className="inline-flex items-center gap-1.5"><Wallet className="h-4 w-4" />{b?.has_estimate ? `Estimate ${money(b.total, trip.currency)}` : "Estimate not available"}</span></p></div>
          <div className="flex items-center gap-2"><Badge tone="teal">Version {it.version}</Badge>{!it.search_used && <Badge tone="amber">No live research</Badge>}</div>
        </div>
        {d.overview && <div className="mt-4 border-t border-sand-200 pt-4"><Markdown>{d.overview}</Markdown></div>}
        <div className="no-print mt-5 flex flex-wrap gap-2">
          <Button variant="secondary" onClick={() => setRegen((r) => !r)}><RefreshCw className="h-4 w-4" />Regenerate itinerary</Button>
          <Button variant="secondary" onClick={() => qc.invalidateQueries({ queryKey: ["itinerary", trip.id] })}>Refresh plan</Button>
          <Link to="../budget" className="btn-secondary"><Wallet className="h-4 w-4" />View budget</Link>
          <Link to="../research" className="btn-secondary"><MapIcon className="h-4 w-4" />View map</Link>
          <Link to="../chat" className="btn-secondary"><MessageSquare className="h-4 w-4" />Back to chat</Link>
          <Button variant="ghost" onClick={() => window.print()}><Printer className="h-4 w-4" />Print</Button>
          <Button variant="ghost" onClick={() => download(it, trip.name)}><Download className="h-4 w-4" />Download</Button>
        </div>
        {regen && <div className="no-print mt-5 border-t border-sand-200 pt-5"><GenerateBox onGenerate={(i) => gen.mutate(i)} busy={gen.isPending} label="Generate a new version" /><p className="mt-2 text-xs text-ink-500">Your current version stays available in the history.</p></div>}
      </section>

      {!it.search_used && <Alert kind="warning">This plan was written without live web research, so prices, opening hours and availability are unverified. Check them before booking.</Alert>}
      {it.budget_error && <Alert kind="info">Budget: {it.budget_error}</Alert>}

      {d.structured && d.days ? (
        <ol className="space-y-5">
          {d.days.map((day) => (
            <li key={day.day} className="card overflow-hidden">
              <div className="flex flex-wrap items-center justify-between gap-2 border-b border-sand-200 bg-lagoon-50 px-5 py-3">
                <div className="flex items-center gap-2">
                  <h3 className="text-lg font-semibold text-lagoon-800">{day.title}</h3>
                  {(day as any)._provider && (
                    <span className="rounded-full bg-lagoon-200/80 px-2 py-0.5 text-[10px] font-medium text-lagoon-800">
                      {(day as any)._provider === "qwen" ? "Qwen 2.5 (Local)" : "Gemini"}
                    </span>
                  )}
                </div>
                <button
                  type="button"
                  className="inline-flex items-center gap-1 rounded-md border border-lagoon-300 bg-white px-2.5 py-1 text-xs font-medium text-lagoon-700 hover:bg-lagoon-100"
                  onClick={() => {
                    setSwappingDay(swappingDay === day.day ? null : day.day);
                    setSwapInstruction("");
                  }}
                >
                  <Sparkles className="h-3.5 w-3.5 text-sun-500" />
                  {swappingDay === day.day ? "Cancel" : "Customize Day"}
                </button>
              </div>
              {swappingDay === day.day && (
                <div className="border-b border-sand-200 bg-sand-50 p-3.5">
                  <p className="mb-1.5 text-xs font-medium text-ink-600">
                    What would you like to change for Day {day.day}? (e.g. "replace dinner with a vegetarian rooftop café")
                  </p>
                  <div className="flex gap-2">
                    <input
                      type="text"
                      className="input text-sm"
                      placeholder="e.g. replace dinner with a budget vegetarian spot"
                      value={swapInstruction}
                      onChange={(e) => setSwapInstruction(e.target.value)}
                      onKeyDown={(e) => {
                        if (e.key === "Enter" && swapInstruction.trim()) {
                          swapMutation.mutate({ day: day.day, instruction: swapInstruction.trim() });
                        }
                      }}
                    />
                    <Button
                      className="!py-1 text-xs"
                      loading={swapMutation.isPending}
                      disabled={!swapInstruction.trim()}
                      onClick={() => swapMutation.mutate({ day: day.day, instruction: swapInstruction.trim() })}
                    >
                      Update Day
                    </Button>
                  </div>
                </div>
              )}
              <div className="space-y-4 p-5">
                {day.intro && <Markdown>{day.intro}</Markdown>}
                {day.sections.length > 0 ? day.sections.map((s, i) => { const P = PERIODS[s.period]; return (
                  <div key={i} className="grid gap-2 sm:grid-cols-[8rem_1fr]">
                    <p className="flex items-center gap-2 text-sm font-semibold text-ink-700"><P.icon className="h-4 w-4 text-sun-500" aria-hidden />{P.label}</p>
                    <Markdown>{s.content}</Markdown></div>); }) : null}
              </div>
            </li>))}
        </ol>
      ) : <section className="card p-6"><p className="mb-3 text-sm text-ink-500">The plan didn’t follow the Day 1 / Day 2 layout, so it’s shown as written.</p><Markdown>{it.plan_markdown ?? ""}</Markdown></section>}

      {d.structured && d.tail && <section className="card p-6"><Markdown>{d.tail}</Markdown></section>}
      {it.research_markdown && <section className="card p-6"><h3 className="text-lg font-semibold">Researcher’s notes</h3><Markdown>{it.research_markdown}</Markdown></section>}

      <div className="no-print flex flex-wrap items-center gap-3">
        <button className="inline-flex items-center gap-1.5 text-sm text-ink-500 underline" onClick={() => setShowRaw((s) => !s)}><FileText className="h-4 w-4" />{showRaw ? "Hide" : "Show"} original AI text</button>
        <span className="text-xs text-ink-400">Generated by {it.model ?? "the AI"} · AI plans can contain mistakes.</span>
      </div>
      {showRaw && <pre className="card overflow-x-auto whitespace-pre-wrap break-words p-5 text-sm">{it.plan_markdown}</pre>}
    </div>
  );
}
