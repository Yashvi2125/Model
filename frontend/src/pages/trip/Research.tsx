import { useQuery } from "@tanstack/react-query";
import L from "leaflet";
import { Calendar, CloudSun, ExternalLink, MapPin, MapPinOff } from "lucide-react";
import { useEffect, useRef } from "react";
import { Link } from "react-router-dom";
import { Markdown } from "../../components/Markdown";
import { Alert, EmptyState, PageLoader, QueryError } from "../../components/ui";
import { useTrip } from "../../layouts/tripContext";
import { api } from "../../lib/api";
import type { Research, ResearchLocation } from "../../lib/types";

function DestinationMap({ locations }: { locations: ResearchLocation[] }) {
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!ref.current || locations.length === 0) return;

    const first = locations[0];
    const map = L.map(ref.current, { scrollWheelZoom: false }).setView([first.lat, first.lon], 11);

    L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
      maxZoom: 18,
      attribution: "© OpenStreetMap contributors",
    }).addTo(map);

    const markers: L.Marker[] = [];

    locations.forEach((loc) => {
      const isDest = loc.is_destination;
      const isApprox = loc.is_approximate;
      const color = isDest ? "#0F7C77" : isApprox ? "#8B5CF6" : "#D97706";
      const pinHtml = `<svg width="28" height="38" viewBox="0 0 28 38"><path d="M14 0C6.3 0 0 6.3 0 14c0 10 14 24 14 24s14-14 14-24C28 6.3 21.7 0 14 0z" fill="${color}"/><circle cx="14" cy="14" r="5.5" fill="#FBF8F2"/></svg>`;

      const pin = L.divIcon({
        className: "",
        iconSize: [28, 38],
        iconAnchor: [14, 38],
        html: pinHtml,
      });

      const popupContent = `
        <div style="font-family: inherit; font-size: 13px; line-height: 1.4;">
          <strong style="font-size: 14px;">${loc.label || loc.name}</strong>
          ${isDest ? '<div style="color: #0F7C77; font-weight: 600; font-size: 11px;">Main Destination</div>' : ""}
          ${isApprox ? '<div style="color: #8B5CF6; font-weight: 600; font-size: 11px;">Approximate location</div>' : ""}
          ${loc.distance_km != null && !isDest ? `<div style="color: #666; font-size: 11px;">${loc.distance_km} km from destination</div>` : ""}
          ${loc.weather ? `<div style="margin-top: 4px; font-weight: 500;">${loc.weather.condition} • ${loc.weather.temp_display}</div>` : ""}
        </div>
      `;

      const marker = L.marker([loc.lat, loc.lon], { icon: pin, title: loc.label || loc.name })
        .addTo(map)
        .bindPopup(popupContent);
      markers.push(marker);
    });

    if (markers.length > 1) {
      const group = L.featureGroup(markers);
      map.fitBounds(group.getBounds().pad(0.15));
    } else if (markers.length === 1) {
      map.setView([locations[0].lat, locations[0].lon], 12);
    }

    return () => {
      map.remove();
    };
  }, [locations]);

  return (
    <div
      ref={ref}
      className="h-72 w-full rounded-lg sm:h-96"
      role="region"
      aria-label="Map showing itinerary destination and locations"
    />
  );
}

export default function ResearchPage() {
  const { trip } = useTrip();
  const q = useQuery({
    queryKey: ["research", trip.id],
    queryFn: () => api<Research>(`/api/trips/${trip.id}/research`),
    refetchInterval: (query) => (query.state.data?.is_resolving ? 1500 : false),
    staleTime: 60_000,
  });

  if (q.isLoading) return <PageLoader label="Looking up the destination and itinerary stops…" />;
  if (q.error || !q.data) return <QueryError error={q.error} retry={() => q.refetch()} />;

  const r = q.data;
  if (r.unavailable_reason) {
    return <EmptyState icon={<MapPinOff className="h-7 w-7" />} title="No destination yet" text={r.unavailable_reason} />;
  }

  const locationsList: ResearchLocation[] =
    r.locations && r.locations.length > 0 ? r.locations : r.location ? [r.location] : [];

  const w = r.weather;

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-2xl font-bold sm:text-3xl">Map &amp; weather{r.destination ? ` — ${r.destination}` : ""}</h2>
        <p className="text-ink-500">
          Interactive map and local weather for your destination and itinerary stops.
        </p>
      </div>

      {r.errors.map((e) => (
        <Alert
          key={e}
          kind="warning"
          action={
            <button className="font-semibold underline" onClick={() => q.refetch()}>
              Retry
            </button>
          }
        >
          {e}
        </Alert>
      ))}

      {r.is_resolving && (
        <div className="flex items-center gap-2 px-3 py-2 text-xs font-medium bg-sand-100 text-ink-700 rounded-lg animate-pulse border border-sand-200">
          <span className="inline-block h-2 w-2 rounded-full bg-lagoon-500 animate-ping" />
          <span>{r.status_message || "Locating remaining itinerary stops on map…"}</span>
        </div>
      )}

      {locationsList.length > 0 && (
        <section className="card overflow-hidden p-2">
          <DestinationMap locations={locationsList} />
          {r.unlocated_stops && r.unlocated_stops.length > 0 && (
            <div className="mt-2 text-xs text-ink-600 bg-sand-50 border border-sand-200 rounded-lg p-2.5">
              <div className="font-semibold text-ink-800 mb-1">Could not locate on map:</div>
              <ul className="list-disc list-inside space-y-0.5">
                {r.unlocated_stops.map((stop, idx) => {
                  const name = typeof stop === "string" ? stop : stop.name;
                  const reason = typeof stop === "string" ? null : stop.reason;
                  return (
                    <li key={idx}>
                      <span className="font-medium text-ink-700">{name}</span>
                      {reason && <span className="text-ink-500"> — {reason}</span>}
                    </li>
                  );
                })}
              </ul>
            </div>
          )}
        </section>
      )}

      {!r.itinerary_version && (
        <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-3 p-4 rounded-xl bg-sand-100 border border-sand-200">
          <div className="flex items-center gap-3">
            <MapPin className="h-5 w-5 text-lagoon-600 shrink-0" />
            <p className="text-sm text-ink-700">
              Showing destination only. Generate an itinerary to see all daily activity stops and restaurants pinned on this map.
            </p>
          </div>
          <Link
            to={`/app/trips/${trip.id}/itinerary`}
            className="btn-secondary text-xs font-semibold shrink-0"
          >
            Go to Itinerary
          </Link>
        </div>
      )}

      {/* Weather card per location */}
      {locationsList.length > 0 && (
        <section className="space-y-3">
          <div className="flex items-center justify-between">
            <h3 className="flex items-center gap-2 text-lg font-semibold">
              <CloudSun className="h-5 w-5 text-sun-500" />
              Weather by location
            </h3>
            <span className="text-xs text-ink-500 font-medium">
              {locationsList.length} {locationsList.length === 1 ? "location" : "locations"} on map
            </span>
          </div>

          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {locationsList.map((loc) => {
              const lw = loc.weather;
              return (
                <div
                  key={`${loc.name}-${loc.lat}-${loc.lon}`}
                  className="card p-4 flex flex-col justify-between border border-sand-200 hover:border-sand-300 transition"
                >
                  <div>
                    <div className="flex items-start justify-between gap-2 mb-2">
                      <div className="min-w-0">
                        <h4 className="font-semibold text-ink-900 truncate" title={loc.label || loc.name}>
                          {loc.label || loc.name}
                        </h4>
                        <p className="text-xs text-ink-500 flex items-center gap-1 mt-0.5">
                          <MapPin className="h-3 w-3 shrink-0" />
                          {loc.is_region
                            ? "Region overview"
                            : loc.is_destination
                            ? "Main destination"
                            : loc.is_approximate
                            ? `Approximate location${loc.distance_km != null ? ` • ${loc.distance_km} km away` : ""}`
                            : loc.distance_km != null
                            ? `${loc.distance_km} km away`
                            : "Itinerary stop"}
                        </p>
                      </div>
                      <span
                        className={`px-2 py-0.5 text-xs font-medium rounded-full shrink-0 ${
                          loc.is_region
                            ? "bg-sand-200 text-ink-700"
                            : loc.is_destination
                            ? "bg-lagoon-100 text-lagoon-800"
                            : loc.is_approximate
                            ? "bg-purple-100 text-purple-800"
                            : "bg-amber-100 text-amber-800"
                        }`}
                      >
                        {loc.is_region
                          ? "Region"
                          : loc.is_destination
                          ? "Destination"
                          : loc.is_approximate
                          ? "Approximate"
                          : "Stop"}
                      </span>
                    </div>

                    {lw ? (
                      <div className="space-y-2.5 mt-3">
                        {lw.date_label && (
                          <div className="flex items-center gap-1 text-[11px] font-medium text-ink-500">
                            <Calendar className="h-3 w-3 text-ink-400 shrink-0" />
                            <span>{lw.date_label}</span>
                          </div>
                        )}

                        <div className="flex items-baseline justify-between">
                          <span className="text-xl font-bold text-ink-900">
                            {lw.temp_display || "Not available"}
                          </span>
                          <span className="text-xs font-medium text-ink-600 bg-sand-100 px-2 py-0.5 rounded">
                            {lw.condition || "Not available"}
                          </span>
                        </div>

                        <div className="grid grid-cols-3 gap-2 pt-2 border-t border-sand-100 text-xs text-ink-600">
                          <div className="flex flex-col items-center p-1.5 bg-sand-50 rounded-lg">
                            <span className="text-[11px] text-ink-400">Humidity</span>
                            <span className="font-semibold mt-0.5">
                              {lw.humidity != null ? `${lw.humidity}%` : "—"}
                            </span>
                          </div>
                          <div className="flex flex-col items-center p-1.5 bg-sand-50 rounded-lg">
                            <span className="text-[11px] text-ink-400">Wind</span>
                            <span className="font-semibold mt-0.5">
                              {lw.wind_speed_kmh != null ? `${lw.wind_speed_kmh} km/h` : "—"}
                            </span>
                          </div>
                          <div className="flex flex-col items-center p-1.5 bg-sand-50 rounded-lg">
                            <span className="text-[11px] text-ink-400">Rain prob.</span>
                            <span className="font-semibold mt-0.5">
                              {lw.rain_chance != null ? `${lw.rain_chance}%` : "—"}
                            </span>
                          </div>
                        </div>

                        {/* Day by day strip for trip dates */}
                        {lw.days && lw.days.length > 0 && (
                          <div className="pt-2 border-t border-sand-100">
                            <p className="text-[11px] font-semibold text-ink-500 mb-1.5">Daily forecast:</p>
                            <div className="space-y-1">
                              {lw.days.map((d) => (
                                <div key={d.date} className="flex items-center justify-between text-[11px] py-0.5">
                                  <span className="text-ink-600 font-medium w-16 shrink-0">
                                    {new Date(d.date + "T00:00:00").toLocaleDateString("en-IN", {
                                      weekday: "short",
                                      day: "numeric",
                                    })}
                                  </span>
                                  <span className="text-ink-500 truncate flex-1 text-center px-1">
                                    {d.condition || "—"}
                                  </span>
                                  <span className="text-ink-800 font-medium shrink-0">
                                    {d.max_c != null && d.min_c != null
                                      ? `${Math.round(d.min_c)}° / ${Math.round(d.max_c)}°`
                                      : d.max_c != null
                                      ? `${Math.round(d.max_c)}°`
                                      : "—"}
                                    {d.rain_chance != null && (
                                      <span className="text-ink-400 ml-1">({d.rain_chance}%)</span>
                                    )}
                                  </span>
                                </div>
                              ))}
                            </div>
                          </div>
                        )}

                        {lw.forecast_note && (
                          <p className="text-[11px] text-ink-500 italic mt-1.5 bg-sand-100/70 rounded px-2 py-1">
                            {lw.forecast_note}
                          </p>
                        )}
                      </div>
                    ) : (
                      <p className="text-xs text-ink-400 italic mt-3">Weather information not available.</p>
                    )}
                  </div>
                </div>
              );
            })}
          </div>
        </section>
      )}

      {/* Destination daily breakdown if forecast is available for trip dates */}
      {w && w.days && w.days.length > 0 && (
        <section className="card p-5">
          <h3 className="flex items-center gap-2 text-lg font-semibold">
            <CloudSun className="h-5 w-5 text-sun-500" />
            {w.covers_trip ? "Daily forecast for your trip dates" : "Destination 7-day outlook"}
          </h3>
          {w.note && <p className="mt-2 text-sm text-sun-700">{w.note}</p>}
          <ul className="mt-4 grid grid-cols-2 gap-3 sm:grid-cols-4 lg:grid-cols-7">
            {w.days.map((d) => (
              <li key={d.date} className="rounded-xl border border-sand-200 p-3 text-sm">
                <p className="font-semibold">
                  {new Date(d.date + "T00:00:00").toLocaleDateString("en-IN", {
                    weekday: "short",
                    day: "numeric",
                    month: "short",
                  })}
                </p>
                <p className="text-ink-500">{d.summary && d.summary !== "—" ? d.summary : "Not available"}</p>
                {d.max_c != null && d.min_c != null ? (
                  <p className="mt-1 font-medium">
                    {Math.round(d.max_c)}° / {Math.round(d.min_c)}°C
                  </p>
                ) : d.max_c != null ? (
                  <p className="mt-1 font-medium">{Math.round(d.max_c)}°C</p>
                ) : (
                  <p className="mt-1 text-xs text-ink-400 italic">Not available</p>
                )}
                {d.rain_chance != null && <p className="text-xs text-ink-500">Rain {d.rain_chance}%</p>}
              </li>
            ))}
          </ul>
        </section>
      )}

      <section className="card p-5">
        <h3 className="text-lg font-semibold">Travel research</h3>
        {r.research_markdown ? (
          <>
            <p className="mt-1 text-sm text-ink-500">
              From the Researcher agent on itinerary v{r.itinerary_version}
              {r.search_used ? ", using live web search." : " — without live web search, so verify details."}
            </p>
            <Markdown>{r.research_markdown}</Markdown>
          </>
        ) : (
          <p className="mt-1 text-ink-500">
            {r.itinerary_version
              ? "The researcher didn’t add notes to this itinerary."
              : "Generate an itinerary and the Researcher agent’s notes appear here."}
            {!r.tavily_configured && " Live web research needs a TAVILY_API_KEY."}
          </p>
        )}
        {r.sources.length > 0 && (
          <div className="mt-4">
            <h4 className="text-sm font-semibold">Links mentioned in the plan</h4>
            <ul className="mt-1 space-y-1 text-sm">
              {r.sources.map((s) => (
                <li key={s} className="break-all">
                  <a
                    className="inline-flex items-start gap-1 text-lagoon-700 underline"
                    href={s}
                    target="_blank"
                    rel="noopener noreferrer nofollow"
                  >
                    <ExternalLink className="mt-0.5 h-3.5 w-3.5 shrink-0" />
                    {s}
                  </a>
                </li>
              ))}
            </ul>
          </div>
        )}
      </section>

      {r.attribution && <p className="text-xs text-ink-500">{r.attribution}</p>}
    </div>
  );
}
