import { useQuery } from "@tanstack/react-query";
import { Luggage, Plus } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router-dom";
import { TripCard } from "../components/TripCard";
import { EmptyState, PageLoader, QueryError } from "../components/ui";
import { api } from "../lib/api";
import type { TripSummary } from "../lib/types";

export default function MyTrips() {
  const q = useQuery({ queryKey: ["trips"], queryFn: () => api<TripSummary[]>("/api/trips") });
  const [filter, setFilter] = useState<"all" | "owner" | "member">("all");
  const trips = (q.data ?? []).filter((t) => filter === "all" || t.my_role === filter);
  return (
    <div>
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-3xl font-bold">My Trips</h1>
        <div className="flex gap-2"><Link to="/app/join" className="btn-secondary">Join a Trip</Link><Link to="/app/trips/new" className="btn-primary"><Plus className="h-4 w-4" />Create a Trip</Link></div>
      </div>
      <div className="mt-5 flex gap-2" role="group" aria-label="Filter trips">
        {([["all", "All"], ["owner", "I organise"], ["member", "Joined"]] as const).map(([k, l]) => (
          <button key={k} className="chip" aria-pressed={filter === k} onClick={() => setFilter(k)}>{l}</button>))}
      </div>
      <div className="mt-6">
        {q.isLoading ? <PageLoader /> : q.error ? <QueryError error={q.error} retry={() => q.refetch()} /> :
          trips.length === 0 ? <EmptyState icon={<Luggage className="h-7 w-7" />} title={q.data?.length ? "No trips match this filter" : "No adventures planned yet."}
            text={q.data?.length ? undefined : "Create your first group trip and invite your friends."}
            action={q.data?.length ? undefined : <Link to="/app/trips/new" className="btn-primary">Create Your First Trip</Link>} /> :
            <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">{trips.map((t) => <TripCard key={t.id} trip={t} />)}</div>}
      </div>
    </div>
  );
}
