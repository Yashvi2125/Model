import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Luggage, Plus } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router-dom";
import { TripCard } from "../components/TripCard";
import { Button, EmptyState, PageLoader, QueryError } from "../components/ui";
import { useToast } from "../context/Toast";
import { api, errorMessage } from "../lib/api";
import type { TripSummary } from "../lib/types";

export default function MyTrips() {
  const qc = useQueryClient();
  const toast = useToast();
  const q = useQuery({ queryKey: ["trips"], queryFn: () => api<TripSummary[]>("/api/trips") });
  const [filter, setFilter] = useState<"all" | "owner" | "member">("all");
  const [tripToDelete, setTripToDelete] = useState<TripSummary | null>(null);

  const deleteMutation = useMutation({
    mutationFn: (tripId: number) => api(`/api/trips/${tripId}`, { method: "DELETE" }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["trips"] });
      toast.success("Trip deleted successfully.");
      setTripToDelete(null);
    },
    onError: (err) => {
      toast.error(errorMessage(err));
    },
  });

  const trips = (q.data ?? []).filter((t) => filter === "all" || t.my_role === filter);
  return (
    <div>
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-3xl font-bold">My Trips</h1>
        <div className="flex flex-wrap gap-2 w-full sm:w-auto">
          <Link to="/app/join" className="btn-secondary flex-1 sm:flex-none">Join a Trip</Link>
          <Link to="/app/trips/new" className="btn-primary flex-1 sm:flex-none"><Plus className="h-4 w-4" />Create a Trip</Link>
        </div>
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
            <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
              {trips.map((t) => (
                <TripCard key={t.id} trip={t} onDelete={(trip) => setTripToDelete(trip)} />
              ))}
            </div>}
      </div>

      {tripToDelete && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4 backdrop-blur-sm"
          role="dialog"
          aria-modal="true"
          aria-labelledby="delete-trip-title"
        >
          <div className="w-full max-w-md rounded-2xl border border-sand-200 bg-white p-6 shadow-xl">
            <h3 id="delete-trip-title" className="text-xl font-bold text-ink-950">Delete Trip</h3>
            <p className="mt-3 text-sm leading-relaxed text-ink-600">
              Are you sure you want to delete <strong className="font-semibold text-ink-900">“{tripToDelete.name}”</strong>?
              This will permanently delete the trip, member preferences, chat history, itineraries, and checklist for everyone.
            </p>
            <div className="mt-6 flex justify-end gap-3">
              <Button
                variant="secondary"
                disabled={deleteMutation.isPending}
                onClick={() => setTripToDelete(null)}
              >
                Cancel
              </Button>
              <Button
                variant="danger"
                loading={deleteMutation.isPending}
                onClick={() => deleteMutation.mutate(tripToDelete.id)}
              >
                Delete trip
              </Button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
