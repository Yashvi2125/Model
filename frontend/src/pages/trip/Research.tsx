import { useQuery } from "@tanstack/react-query";
import L from "leaflet";
import { CloudSun, ExternalLink, MapPinOff } from "lucide-react";
import { useEffect, useRef } from "react";
import { Markdown } from "../../components/Markdown";
import { Alert, EmptyState, PageLoader, QueryError } from "../../components/ui";
import { useTrip } from "../../layouts/tripContext";
import { api } from "../../lib/api";
import type { Research } from "../../lib/types";

function DestinationMap({ lat, lon, label }: { lat: number; lon: number; label: string }) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!ref.current) return;
    const map = L.map(ref.current, { scrollWheelZoom: false }).setView([lat, lon], 11);
    L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", { maxZoom: 18, attribution: "© OpenStreetMap contributors" }).addTo(map);
    const pin = L.divIcon({ className: "", iconSize: [28, 38], iconAnchor: [14, 38],
      html: '<svg width="28" height="38" viewBox="0 0 28 38"><path d="M14 0C6.3 0 0 6.3 0 14c0 10 14 24 14 24s14-14 14-24C28 6.3 21.7 0 14 0z" fill="#0F7C77"/><circle cx="14" cy="14" r="5.5" fill="#FBF8F2"/></svg>' });
    L.marker([lat, lon], { icon: pin, title: label }).addTo(map).bindPopup(label);
    return () => { map.remove(); };
  }, [lat, lon, label]);
  return <div ref={ref} className="h-72 w-full sm:h-96" role="region" aria-label={`Map of ${label}`} />;
}

export default function ResearchPage() {
  const { trip } = useTrip();
  const q = useQuery({ queryKey: ["research", trip.id], queryFn: () => api<Research>(`/api/trips/${trip.id}/research`), staleTime: 60_000 });
  if (q.isLoading) return <PageLoader label="Looking up the destination…" />;
  if (q.error || !q.data) return <QueryError error={q.error} retry={() => q.refetch()} />;
  const r = q.data;
  if (r.unavailable_reason) return <EmptyState icon={<MapPinOff className="h-7 w-7" />} title="No destination yet" text={r.unavailable_reason} />;
  const w = r.weather;
  return (
    <div className="space-y-6">
      <div><h2 className="text-2xl font-bold">Map &amp; weather{r.destination ? ` — ${r.destination}` : ""}</h2>
        <p className="text-ink-500">The pin marks the destination only. Individual attractions in the itinerary haven’t been verified on a map.</p></div>
      {r.errors.map((e) => <Alert key={e} kind="warning" action={<button className="font-semibold underline" onClick={() => q.refetch()}>Retry</button>}>{e}</Alert>)}
      {r.location && <section className="card overflow-hidden p-2"><DestinationMap lat={r.location.lat} lon={r.location.lon} label={[r.location.name, r.location.admin, r.location.country].filter(Boolean).join(", ")} /></section>}
      {w && (
        <section className="card p-5"><h3 className="flex items-center gap-2 text-lg font-semibold"><CloudSun className="h-5 w-5 text-sun-500" />{w.covers_trip ? "Forecast for your trip dates" : "Current outlook"}</h3>
          {w.note && <p className="mt-2 text-sm text-sun-700">{w.note}</p>}
          <ul className="mt-4 grid grid-cols-2 gap-3 sm:grid-cols-4 lg:grid-cols-7">{w.days.map((d) => (
            <li key={d.date} className="rounded-xl border border-sand-200 p-3 text-sm"><p className="font-semibold">{new Date(d.date + "T00:00:00").toLocaleDateString("en-IN", { weekday: "short", day: "numeric", month: "short" })}</p>
              <p className="text-ink-500">{d.summary}</p><p className="mt-1 font-medium">{Math.round(d.max_c)}° / {Math.round(d.min_c)}°C</p>
              {d.rain_chance !== null && <p className="text-xs text-ink-500">Rain {d.rain_chance}%</p>}</li>))}</ul></section>)}
      <section className="card p-5"><h3 className="text-lg font-semibold">Travel research</h3>
        {r.research_markdown ? <><p className="mt-1 text-sm text-ink-500">From the Researcher agent on itinerary v{r.itinerary_version}{r.search_used ? ", using live web search." : " — without live web search, so verify details."}</p><Markdown>{r.research_markdown}</Markdown></> :
          <p className="mt-1 text-ink-500">{r.itinerary_version ? "The researcher didn’t add notes to this itinerary." : "Generate an itinerary and the Researcher agent’s notes appear here."}{!r.tavily_configured && " Live web research needs a TAVILY_API_KEY."}</p>}
        {r.sources.length > 0 && <div className="mt-4"><h4 className="text-sm font-semibold">Links mentioned in the plan</h4>
          <ul className="mt-1 space-y-1 text-sm">{r.sources.map((s) => <li key={s} className="break-all"><a className="inline-flex items-start gap-1 text-lagoon-700 underline" href={s} target="_blank" rel="noopener noreferrer nofollow"><ExternalLink className="mt-0.5 h-3.5 w-3.5 shrink-0" />{s}</a></li>)}</ul></div>}
      </section>
      {r.attribution && <p className="text-xs text-ink-500">{r.attribution}</p>}
    </div>
  );
}
