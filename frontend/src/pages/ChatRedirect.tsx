import { useQuery } from "@tanstack/react-query";
import { MessagesSquare } from "lucide-react";
import { Link, Navigate } from "react-router-dom";
import { EmptyState, PageLoader, QueryError } from "../components/ui";
import { api } from "../lib/api";
import type { TripSummary } from "../lib/types";

export default function ChatRedirect() {
  const q = useQuery({ queryKey: ["trips"], queryFn: () => api<TripSummary[]>("/api/trips") });
  if (q.isLoading) return <PageLoader />;
  if (q.error) return <QueryError error={q.error} retry={() => q.refetch()} />;
  const trips = [...(q.data ?? [])].sort((a, b) => (b.last_accessed_at ?? "").localeCompare(a.last_accessed_at ?? ""));
  if (!trips.length)
    return <EmptyState icon={<MessagesSquare />} title="No group chats yet" text="Create or join a trip and its group chat appears here."
      action={<Link className="btn-primary" to="/app/trips/new">Create your first trip</Link>} />;
  return <Navigate to={`/app/trips/${trips[0]!.id}/chat`} replace />;
}
