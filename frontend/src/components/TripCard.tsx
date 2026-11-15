import { CalendarDays, Users, Wallet } from "lucide-react";
import { Link } from "react-router-dom";
import { dateRange, dayCount, money } from "../lib/format";
import type { TripSummary } from "../lib/types";
import { Badge } from "./ui";

export const statusLabel = (s: string) => (s === "itinerary_ready" ? "Itinerary ready" : "Planning");

export function TripCard({ trip }: { trip: TripSummary }) {
  const budget = trip.budget_total ?? (trip.budget_per_person ? trip.budget_per_person * trip.travelers_count : null);
  return (
    <article className="card flex flex-col p-5 transition-shadow hover:shadow-md">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <h3 className="truncate text-lg font-semibold">{trip.name}</h3>
          <p className="truncate text-ink-500">{trip.destination ?? "Destination undecided"}</p>
        </div>
        <Badge tone={trip.status === "itinerary_ready" ? "teal" : "amber"}>{statusLabel(trip.status)}</Badge>
      </div>
      <dl className="mt-4 space-y-2 text-sm text-ink-700">
        <div className="flex items-center gap-2"><CalendarDays className="h-4 w-4 text-ink-400" aria-hidden /><dt className="sr-only">Dates</dt><dd>{dateRange(trip.start_date, trip.end_date)} · {dayCount(trip.start_date, trip.end_date)} days</dd></div>
        <div className="flex items-center gap-2"><Users className="h-4 w-4 text-ink-400" aria-hidden /><dt className="sr-only">Participants</dt><dd>{trip.member_count} joined · {trip.travelers_count} travelling{trip.my_role === "owner" ? " · you organise" : ""}</dd></div>
        {budget !== null && <div className="flex items-center gap-2"><Wallet className="h-4 w-4 text-ink-400" aria-hidden /><dt className="sr-only">Budget</dt><dd>{money(budget, trip.currency)} group budget</dd></div>}
      </dl>
      <div className="mt-5 flex flex-wrap gap-2 pt-1">
        <Link to={`/app/trips/${trip.id}/chat`} className="btn-primary !py-2">View Trip</Link>
        <Link to={`/app/trips/${trip.id}/itinerary`} className="btn-secondary !py-2">Itinerary</Link>
      </div>
    </article>
  );
}
