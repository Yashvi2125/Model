import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CircleCheck, MessageCircle, ScanSearch, ThumbsDown, ThumbsUp } from "lucide-react";
import { Alert, Badge, Button, EmptyState, PageLoader, QueryError } from "../../components/ui";
import { useAuth } from "../../context/AuthContext";
import { useToast } from "../../context/Toast";
import { useTrip } from "../../layouts/tripContext";
import { api, errorMessage, post } from "../../lib/api";
import type { Conflict, ConflictsResult } from "../../lib/types";
import { Link, useNavigate } from "react-router-dom";

function ConflictCard({ c, tripId, memberCount, isOwner }: { c: Conflict; tripId: number; memberCount: number; isOwner: boolean }) {
  const { user } = useAuth(); const qc = useQueryClient(); const toast = useToast(); const navigate = useNavigate();
  const base = `/api/trips/${tripId}/conflicts/${c.id}`;
  const upd = (d: ConflictsResult) => qc.setQueryData(["conflicts", tripId], d);
  const vote = useMutation({ mutationFn: (v: "agree" | "disagree") => post<ConflictsResult>(`${base}/vote`, { vote: v }), onSuccess: upd, onError: (e) => toast.error(errorMessage(e)) });
  const discuss = useMutation({ mutationFn: () => post<ConflictsResult>(`${base}/discuss`), onSuccess: () => { toast.success("Posted to the group chat."); navigate("../chat"); }, onError: (e) => toast.error(errorMessage(e)) });
  const dismiss = useMutation({ mutationFn: () => post<ConflictsResult>(`${base}/dismiss`), onSuccess: upd, onError: (e) => toast.error(errorMessage(e)) });
  const mine = c.votes[String(user!.id)];
  const agrees = Object.values(c.votes).filter((v) => v === "agree").length;
  const disagrees = Object.values(c.votes).filter((v) => v === "disagree").length;
  return (
    <article className="card card-hover p-6">
      <header className="flex flex-wrap items-start justify-between gap-2">
        <div><h3 className="text-lg font-semibold">{c.title}</h3><p className="mt-0.5 text-ink-500">{c.description}</p></div>
        {c.status === "accepted" ? <Badge tone="teal"><CircleCheck className="h-3 w-3" />Everyone agreed</Badge> : <Badge tone="amber">Not decided</Badge>}
      </header>
      {c.positions.length > 0 && <ul className="mt-3 space-y-1 text-[15px]">{c.positions.map((p, i) => <li key={i}><span className="font-semibold">{p.name}</span> — {p.detail}</li>)}</ul>}
      {c.suggestion ? (
        <div className="mt-4 rounded-2xl border border-lagoon-200 bg-gradient-to-br from-lagoon-50 to-white p-5">
          <p className="text-sm font-semibold text-lagoon-800">Suggested compromise (from MileMates AI)</p>
          <p className="mt-1 text-[15px]">{c.suggestion}</p>
          <p className="mt-2 text-xs text-ink-500">A suggestion isn’t a decision. It’s marked as agreed only once all {memberCount} members agree. So far: {agrees} agree, {disagrees} disagree.</p>
          <div className="mt-3 flex flex-wrap gap-2">
            <button className="chip" aria-pressed={mine === "agree"} disabled={vote.isPending} onClick={() => vote.mutate("agree")}><ThumbsUp className="h-4 w-4" />I agree</button>
            <button className="chip" aria-pressed={mine === "disagree"} disabled={vote.isPending} onClick={() => vote.mutate("disagree")}><ThumbsDown className="h-4 w-4" />I disagree</button>
            <Button variant="ghost" className="!py-1.5" loading={discuss.isPending} onClick={() => discuss.mutate()}><MessageCircle className="h-4 w-4" />Discuss in chat</Button>
          </div>
        </div>
      ) : (
        <div className="mt-4 flex flex-wrap items-center gap-3 rounded-2xl bg-sand-100 p-4 text-sm text-ink-700">No compromise has been proposed yet.
          <Button variant="ghost" className="!py-1.5" loading={discuss.isPending} onClick={() => discuss.mutate()}><MessageCircle className="h-4 w-4" />Discuss in chat</Button></div>)}
      {isOwner && <div className="mt-3 text-right"><button className="text-sm text-ink-500 underline" disabled={dismiss.isPending} onClick={() => dismiss.mutate()}>Dismiss this item</button></div>}
    </article>
  );
}

function emptyCopy(res: ConflictsResult | undefined, checked: boolean) {
  if (!res || res.member_count < 2)
    return { title: "You’re the only member so far", text: "Disagreements need at least two people. Invite someone from the Members & invite tab; once they’ve saved their preferences you can compare them here." };
  if (res.members_sharing < 2)
    return { title: "Not enough preferences to compare", text: `Only ${res.members_sharing} of ${res.member_count} members have shared preferences. Ask everyone to fill in the Preferences tab, then check again.` };
  if (checked)
    return { title: "No disagreements found", text: "Members’ saved preferences don’t clash (budgets within 25% of each other, shared activities, matching dates and destination)." };
  return { title: "Nothing checked yet", text: "Press “Check for disagreements” to compare everyone’s saved preferences." };
}

export default function Conflicts() {
  const { trip } = useTrip();
  const qc = useQueryClient(); const toast = useToast();
  const q = useQuery({ queryKey: ["conflicts", trip.id], queryFn: () => api<ConflictsResult>(`/api/trips/${trip.id}/conflicts`) });
  const analyze = useMutation({
    mutationFn: () => post<ConflictsResult>(`/api/trips/${trip.id}/conflicts/analyze`),
    onSuccess: (d) => { qc.setQueryData(["conflicts", trip.id], d); setChecked(true); },
    onError: (e) => toast.error(errorMessage(e)),
  });
  const [checked, setChecked] = useState(false);
  const res = q.data; // single source of truth: votes, dismissals and live updates all write to this cache
  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div><h2 className="text-2xl font-bold sm:text-3xl">Find common ground</h2><p className="max-w-xl text-ink-500">Compares what members have saved in Preferences, lists where you differ, and proposes a compromise for the group to vote on.</p></div>
        <Button onClick={() => analyze.mutate()} loading={analyze.isPending}><ScanSearch className="h-4 w-4" />{analyze.isPending ? "Analysing…" : "Check for disagreements"}</Button>
      </div>
      {analyze.data?.ai_error && <Alert kind="warning">The differences below were found automatically, but compromises couldn’t be suggested: {analyze.data.ai_error}</Alert>}
      {q.isLoading ? <PageLoader /> : q.error ? <QueryError error={q.error} retry={() => q.refetch()} /> :
        res && res.conflicts.length > 0 ? <div className="space-y-4">{res.conflicts.map((c) => <ConflictCard key={c.id} c={c} tripId={trip.id} memberCount={res.member_count} isOwner={trip.my_role === "owner"} />)}</div> :
          <EmptyState icon={<ScanSearch className="h-7 w-7" />} {...emptyCopy(res, checked)}
            action={res && res.member_count >= 2 && res.members_sharing < res.member_count ? <Link className="btn-secondary" to="../preferences">Open Preferences</Link> : undefined} />}
    </div>
  );
}

