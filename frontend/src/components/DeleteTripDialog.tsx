import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useToast } from "../context/Toast";
import { api, errorMessage } from "../lib/api";
import type { TripSummary } from "../lib/types";
import { Button } from "./ui";

/** Confirmation dialog + delete request, shared by Overview and My Trips. */
export function DeleteTripDialog({ trip, onClose }: { trip: TripSummary; onClose: () => void }) {
  const qc = useQueryClient();
  const toast = useToast();
  const del = useMutation({
    mutationFn: (tripId: number) => api(`/api/trips/${tripId}`, { method: "DELETE" }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["trips"] });
      toast.success("Trip deleted successfully.");
      onClose();
    },
    onError: (err) => {
      toast.error(errorMessage(err));
    },
  });
  return (
    <div
      className="fixed inset-0 z-50 flex animate-fade-in items-center justify-center bg-ink-950/50 p-4 backdrop-blur-md"
      role="dialog"
      aria-modal="true"
      aria-labelledby="delete-trip-title"
    >
      <div className="w-full max-w-md animate-fade-up rounded-[2rem] border border-white bg-white p-7 shadow-float">
        <h3 id="delete-trip-title" className="text-xl font-bold text-ink-900">Delete Trip</h3>
        <p className="mt-3 text-sm leading-relaxed text-ink-700">
          Are you sure you want to delete <strong className="font-semibold text-ink-900">“{trip.name}”</strong>?
          This will permanently delete the trip, member preferences, chat history, itineraries, and checklist for everyone.
        </p>
        <div className="mt-6 flex justify-end gap-3">
          <Button variant="secondary" disabled={del.isPending} onClick={onClose}>Cancel</Button>
          <Button variant="danger" loading={del.isPending} onClick={() => del.mutate(trip.id)}>Delete trip</Button>
        </div>
      </div>
    </div>
  );
}