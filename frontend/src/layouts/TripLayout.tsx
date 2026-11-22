import { useQuery } from "@tanstack/react-query";
import { CalendarDays, Check, Copy, MapPin, Wifi, WifiOff } from "lucide-react";
import { useState } from "react";
import { Link, NavLink, Outlet, useParams } from "react-router-dom";
import { Alert, Badge, EmptyState, PageLoader } from "../components/ui";
import { useTripSocket } from "../hooks/useTripSocket";
import { api } from "../lib/api";
import { dateRange, dayCount } from "../lib/format";
import type { AIStatus, TripDetail } from "../lib/types";

const TABS = [
  ["chat", "Chat"], ["preferences", "Preferences"], ["conflicts", "Conflicts"], ["itinerary", "Itinerary"],
  ["budget", "Budget"], ["research", "Map & weather"], ["checklist", "Checklist"], ["members", "Members & invite"],
] as const;

export default function TripLayout() {
  const id = Number(useParams().tripId);
  const trip = useQuery({ queryKey: ["trip", id], queryFn: () => api<TripDetail>(`/api/trips/${id}`), enabled: Number.isFinite(id) });
  const ai = useQuery({ queryKey: ["ai-status"], queryFn: () => api<AIStatus>("/api/ai/status"), staleTime: 300_000 });
  const socket = useTripSocket(id);
  const [copied, setCopied] = useState(false);

  if (trip.isLoading) return <PageLoader label="Opening trip…" />;
  if (trip.error || !trip.data)
    return <EmptyState title="We couldn’t open this trip" text={trip.error instanceof Error ? trip.error.message : "It may not exist, or you may not be a member."}
      action={<Link to="/app/trips" className="btn-primary">Back to My Trips</Link>} />;
  const t = trip.data;
  if (socket.status === "denied")
    return <EmptyState title="You’re not a member of this trip" action={<Link to="/app/join" className="btn-primary">Join with a code</Link>} />;

  const copy = async () => {
    try { await navigator.clipboard.writeText(t.code); setCopied(true); setTimeout(() => setCopied(false), 1800); } catch { /* clipboard blocked */ }
  };

  return (
    <div>
      <header className="no-print">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0">
            <h1 className="truncate text-2xl font-bold sm:text-3xl">{t.name}</h1>
            <p className="mt-1 flex flex-wrap items-center gap-x-4 gap-y-1 text-sm text-ink-500">
              <span className="inline-flex items-center gap-1.5"><MapPin className="h-4 w-4" aria-hidden />{t.destination ?? "Destination undecided"}</span>
              <span className="inline-flex items-center gap-1.5"><CalendarDays className="h-4 w-4" aria-hidden />{dateRange(t.start_date, t.end_date)} · {dayCount(t.start_date, t.end_date)} days</span>
            </p>
          </div>
          <div className="flex items-center gap-2">
            <Badge tone={socket.status === "open" ? "teal" : "amber"}>
              {socket.status === "open" ? <Wifi className="h-3 w-3" aria-hidden /> : <WifiOff className="h-3 w-3" aria-hidden />}
              {socket.status === "open" ? "Live" : "Reconnecting…"}</Badge>
            <button onClick={copy} className="btn-secondary !py-1.5 text-sm" aria-label={`Copy trip code ${t.code}`}>
              {copied ? <Check className="h-4 w-4" /> : <Copy className="h-4 w-4" />}<span className="font-mono tracking-wider">{t.code}</span></button>
          </div>
        </div>
        {ai.data && !ai.data.ready && <div className="mt-4"><Alert kind="warning">{ai.data.notes.join(" ")} The rest of the app still works.</Alert></div>}
        {ai.data?.ready && !ai.data.tavily_configured && <div className="mt-4"><Alert kind="info">Live web research is off (no TAVILY_API_KEY), so itineraries rely on the AI’s general knowledge.</Alert></div>}
        <nav aria-label="Trip sections" className="-mx-4 mt-5 overflow-x-auto border-b border-sand-200 px-4 sm:mx-0 sm:px-0">
          <ul className="flex min-w-max gap-1">
            {TABS.map(([to, label]) => (
              <li key={to}><NavLink to={to} className={({ isActive }) => `inline-flex items-center min-h-[44px] whitespace-nowrap border-b-2 px-3.5 py-2 text-[14px] sm:text-[15px] font-medium transition-colors ${isActive ? "border-lagoon-600 text-lagoon-800" : "border-transparent text-ink-500 hover:text-ink-900"}`}>{label}</NavLink></li>))}
          </ul>
        </nav>
      </header>
      <div className="mt-6"><Outlet context={{ trip: t, socket }} /></div>
    </div>
  );
}
