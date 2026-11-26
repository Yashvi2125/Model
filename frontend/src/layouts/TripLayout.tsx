import { useQuery } from "@tanstack/react-query";
import { CalendarDays, Check, Copy, MapPin, Users, Wifi, WifiOff } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { Link, NavLink, Outlet, useLocation, useParams } from "react-router-dom";
import { Alert, EmptyState, PageLoader } from "../components/ui";
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
  const tabsRef = useRef<HTMLElement>(null);
  const loc = useLocation();
  // Keep the active tab visible when the tab bar scrolls sideways on small screens.
  useEffect(() => {
    const nav = tabsRef.current;
    const a = nav?.querySelector<HTMLElement>('[aria-current="page"]');
    if (nav && a) nav.scrollTo?.({ left: a.offsetLeft - nav.clientWidth / 2 + a.clientWidth / 2, behavior: "smooth" });
  }, [loc.pathname, trip.data]);

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
  const live = socket.status === "open";

  return (
    <div>
      <header className="no-print">
        <div className="surface-soft rounded-2xl px-4 py-3 sm:rounded-3xl sm:px-6 sm:py-4">
          <div className="pointer-events-none absolute inset-0 bg-dots-dark opacity-60" aria-hidden />
          <div className="pointer-events-none absolute -right-6 -top-10 h-24 w-24 rounded-full bg-sun-500/80 sm:h-28 sm:w-28" aria-hidden style={{ boxShadow: "0 0 60px 16px rgba(233,162,59,.25)" }} />
          <div className="relative flex items-start justify-between gap-3">
            <div className="min-w-0 flex-1">
              <div className="flex items-center gap-2 sm:gap-3">
                <h1 className="min-w-0 truncate text-xl font-bold sm:text-3xl">{t.name}</h1>
                <span className={`inline-flex shrink-0 items-center gap-1 rounded-full px-2 py-0.5 text-[11px] font-bold ring-1 ring-inset sm:gap-1.5 sm:px-2.5 sm:text-xs ${live ? "bg-white text-lagoon-700 ring-lagoon-200" : "bg-sun-100 text-sun-700 ring-sun-500/40"}`}>
                  {live ? <Wifi className="hidden h-3 w-3 sm:block" aria-hidden /> : <WifiOff className="h-3 w-3" aria-hidden />}
                  {live ? "Live" : "Reconnecting…"}
                  {live && <span className="relative ml-0.5 flex h-2 w-2"><span className="absolute inset-0 animate-pulse-ring rounded-full bg-emerald-400" /><span className="relative h-2 w-2 rounded-full bg-emerald-500" /></span>}
                </span>
              </div>
              <p className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-0.5 text-xs text-ink-700 sm:gap-x-4 sm:text-sm">
                <span className="inline-flex items-center gap-1"><MapPin className="h-3.5 w-3.5 text-lagoon-600 sm:h-4 sm:w-4" aria-hidden />{t.destination ?? "Destination undecided"}</span>
                <span className="inline-flex items-center gap-1"><CalendarDays className="h-3.5 w-3.5 text-lagoon-600 sm:h-4 sm:w-4" aria-hidden />{dateRange(t.start_date, t.end_date)} · {dayCount(t.start_date, t.end_date)} days</span>
                <span className="inline-flex items-center gap-1"><Users className="h-3.5 w-3.5 text-lagoon-600 sm:h-4 sm:w-4" aria-hidden />{t.members.length} {t.members.length === 1 ? "member" : "members"}</span>
              </p>
            </div>
            <button onClick={copy} className="btn-secondary !min-h-[40px] shrink-0 !gap-1.5 !px-3 !py-1.5 text-xs sm:!px-4 sm:text-sm" aria-label={`Copy trip code ${t.code}`}>
              {copied ? <Check className="h-4 w-4 text-lagoon-600" /> : <Copy className="h-4 w-4" />}<span className="font-mono tracking-[.15em] sm:tracking-[.2em]">{t.code}</span></button>
          </div>
        </div>
        {ai.data && !ai.data.ready && <div className="mt-3"><Alert kind="warning">{ai.data.notes.join(" ")} The rest of the app still works.</Alert></div>}
        {ai.data?.ready && !ai.data.tavily_configured && <div className="mt-3"><Alert kind="info">Live web research is off (no TAVILY_API_KEY), so itineraries rely on the AI’s general knowledge.</Alert></div>}
        <nav ref={tabsRef} aria-label="Trip sections" className="no-scrollbar -mx-3 mt-2 overflow-x-auto px-3 py-1.5 sm:-mx-6 sm:px-6 lg:sticky lg:top-2 lg:z-20 lg:mx-0 lg:px-0">
          <ul className="glass flex min-w-max gap-1 rounded-2xl p-1.5 shadow-card">
            {TABS.map(([to, label]) => (
              <li key={to}><NavLink to={to} className={({ isActive }) => `inline-flex min-h-[40px] items-center whitespace-nowrap rounded-xl px-3.5 py-2 text-[14px] font-semibold transition-all duration-200 sm:text-[15px] ${isActive ? "bg-lagoon-50 text-lagoon-800 shadow-sm ring-1 ring-lagoon-200" : "text-ink-500 hover:bg-sand-100 hover:text-ink-900"}`}>{label}</NavLink></li>))}
          </ul>
        </nav>
      </header>
      <div className="mt-3 animate-fade-up sm:mt-4"><Outlet context={{ trip: t, socket }} /></div>
    </div>
  );
}
