import { ArrowUpRight, CalendarDays, MapPin, Trash2, Users, Wallet } from "lucide-react";
import { Link } from "react-router-dom";
import { dateRange, dayCount, money } from "../lib/format";
import type { TripSummary } from "../lib/types";
import { Badge } from "./ui";

export const statusLabel = (s: string) => (s === "itinerary_ready" ? "Itinerary ready" : "Planning");

const COVERS = [
  "from-lagoon-100 via-lagoon-50 to-sun-100",
  "from-sun-100 via-sand-100 to-lagoon-100",
  "from-lagoon-200/70 via-lagoon-50 to-white",
  "from-coral-100 via-sun-100 to-lagoon-50",
];

export function TripCard({ trip, onDelete }: { trip: TripSummary; onDelete?: (trip: TripSummary) => void }) {
  const budget = trip.budget_total ?? (trip.budget_per_person ? trip.budget_per_person * trip.travelers_count : null);
  const cover = COVERS[trip.id % COVERS.length];
  const ready = trip.status === "itinerary_ready";
  return (
    <article className="card card-hover group flex flex-col overflow-hidden">
      <div className={`relative h-28 overflow-hidden bg-gradient-to-br ${cover}`}>
        <div className="absolute inset-0 bg-dots-dark" aria-hidden />
        <svg viewBox="0 0 400 120" className="absolute inset-x-0 bottom-0 w-full" preserveAspectRatio="none" aria-hidden>
          <path d="M0 120 L0 80 L70 40 L130 76 L210 24 L290 78 L350 52 L400 76 L400 120Z" fill="#14958F" opacity=".22" />
          <path d="M0 120 L0 98 Q100 64 200 98 T400 90 L400 120Z" fill="#0F7C77" opacity=".32" />
        </svg>
        <div className="absolute right-6 top-5 h-8 w-8 rounded-full bg-sun-500 opacity-90 shadow-[0_0_40px_8px_rgba(233,162,59,.45)]" aria-hidden />
        <div className="absolute left-5 top-4 flex items-center gap-2">
          <Badge tone={ready ? "teal" : "amber"}>{statusLabel(trip.status)}</Badge>
        </div>
        {trip.my_role === "owner" && onDelete && (
          <button
            type="button"
            onClick={(e) => {
              e.preventDefault();
              e.stopPropagation();
              onDelete(trip);
            }}
            className="absolute bottom-3 right-3 flex min-h-[44px] min-w-[44px] items-center justify-center rounded-xl bg-white/80 text-ink-700 shadow-sm backdrop-blur transition-colors hover:bg-coral-500 hover:text-white"
            title={`Delete ${trip.name}`}
            aria-label={`Delete ${trip.name}`}
          >
            <Trash2 className="h-4 w-4" />
          </button>
        )}
      </div>
      <div className="flex flex-1 flex-col p-5">
        <h3 className="truncate text-lg font-semibold">{trip.name}</h3>
        <p className="mt-0.5 flex items-center gap-1.5 truncate text-ink-500"><MapPin className="h-3.5 w-3.5 shrink-0 text-lagoon-600" aria-hidden />{trip.destination ?? "Destination undecided"}</p>
        <dl className="mt-4 space-y-2.5 text-sm text-ink-700">
          <div className="flex items-center gap-2.5"><span className="flex h-7 w-7 items-center justify-center rounded-lg bg-sand-100 text-ink-500"><CalendarDays className="h-3.5 w-3.5" aria-hidden /></span><dt className="sr-only">Dates</dt><dd>{dateRange(trip.start_date, trip.end_date)} · {dayCount(trip.start_date, trip.end_date)} days</dd></div>
          <div className="flex items-center gap-2.5"><span className="flex h-7 w-7 items-center justify-center rounded-lg bg-sand-100 text-ink-500"><Users className="h-3.5 w-3.5" aria-hidden /></span><dt className="sr-only">Participants</dt><dd>{trip.member_count} joined · {trip.travelers_count} travelling{trip.my_role === "owner" ? " · you organise" : ""}</dd></div>
          {budget !== null && <div className="flex items-center gap-2.5"><span className="flex h-7 w-7 items-center justify-center rounded-lg bg-sand-100 text-ink-500"><Wallet className="h-3.5 w-3.5" aria-hidden /></span><dt className="sr-only">Budget</dt><dd>{money(budget, trip.currency)} group budget</dd></div>}
        </dl>
        <div className="mt-auto flex flex-wrap gap-2 pt-5">
          <Link to={`/app/trips/${trip.id}/chat`} className="btn-primary !py-2">View Trip<ArrowUpRight className="h-4 w-4" aria-hidden /></Link>
          <Link to={`/app/trips/${trip.id}/itinerary`} className="btn-secondary !py-2">Itinerary</Link>
        </div>
      </div>
    </article>
  );
}
