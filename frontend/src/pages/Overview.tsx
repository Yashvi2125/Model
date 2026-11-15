import { useQuery } from "@tanstack/react-query";
import { Luggage, Plus } from "lucide-react";
import { Link } from "react-router-dom";
import { TripCard } from "../components/TripCard";
import { EmptyState, PageLoader, QueryError } from "../components/ui";
import { useAuth } from "../context/AuthContext";
import { api } from "../lib/api";
import { todayISO } from "../lib/format";
import type { TripSummary } from "../lib/types";

function Section({ title, trips }: { title: string; trips: TripSummary[] }) {
  if (!trips.length) return null;
  return (
    <section className="mt-10">
      <h2 className="mb-4 text-xl font-semibold">{title}</h2>
      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">{trips.map((t) => <TripCard key={t.id} trip={t} />)}</div>
    </section>
  );
}

export default function Overview() {
  const { user } = useAuth();
  const q = useQuery({ queryKey: ["trips"], queryFn: () => api<TripSummary[]>("/api/trips") });
  const today = todayISO();
  const trips = q.data ?? [];
  const upcoming = trips.filter((t) => t.end_date >= today);
  const joined = trips.filter((t) => t.my_role === "member");
  const recent = [...trips].filter((t) => t.last_accessed_at).sort((a, b) => b.last_accessed_at!.localeCompare(a.last_accessed_at!)).slice(0, 3);

  return (
    <div>
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-3xl font-bold sm:text-4xl">Hello, {user!.name.split(" ")[0]}</h1>
          <p className="mt-1 text-ink-500">Create a trip, invite your group, and let TripMate AI help you agree on a plan.</p>
        </div>
        <Link to="/app/trips/new" className="btn-primary"><Plus className="h-4 w-4" />Create New Trip</Link>
      </div>

      {q.isLoading ? <PageLoader /> : q.error ? <div className="mt-8"><QueryError error={q.error} retry={() => q.refetch()} /></div> :
        trips.length === 0 ? (
          <div className="mt-8">
            <EmptyState icon={<Luggage className="h-7 w-7" />} title="No adventures planned yet."
              text="Create your first group trip and invite your friends — or join one with a trip code."
              action={<div className="flex flex-wrap justify-center gap-3"><Link to="/app/trips/new" className="btn-primary">Create Your First Trip</Link><Link to="/app/join" className="btn-secondary">Join a Trip</Link></div>} />
          </div>
        ) : (
          <>
            <Section title="Upcoming trips" trips={upcoming} />
            <Section title="Trips you’ve joined" trips={joined} />
            <Section title="Recently opened" trips={recent} />
            {upcoming.length === 0 && <p className="mt-8 text-ink-500">All your trips have already ended. <Link className="font-semibold text-lagoon-700 underline" to="/app/trips">See them in My Trips</Link>.</p>}
          </>
        )}
    </div>
  );
}
