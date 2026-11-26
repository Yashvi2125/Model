import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Check, Copy, Link2, RefreshCw, Share2 } from "lucide-react";
import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { Avatar, Badge, Button } from "../../components/ui";
import { useAuth } from "../../context/AuthContext";
import { useToast } from "../../context/Toast";
import { useTrip } from "../../layouts/tripContext";
import { del, errorMessage, patch, post } from "../../lib/api";
import { shortDate } from "../../lib/format";
import type { TripDetail } from "../../lib/types";

export default function Members() {
  const { trip, socket } = useTrip();
  const { user } = useAuth();
  const qc = useQueryClient(); const toast = useToast(); const navigate = useNavigate();
  const [copied, setCopied] = useState("");
  const owner = trip.my_role === "owner";
  const link = `${location.origin}/join/${trip.code}`;
  const set = (t: TripDetail) => { qc.setQueryData(["trip", trip.id], t); qc.invalidateQueries({ queryKey: ["trips"] }); };
  const err = (e: unknown) => toast.error(errorMessage(e));

  const copy = async (what: string, value: string) => { try { await navigator.clipboard.writeText(value); setCopied(what); setTimeout(() => setCopied(""), 1800); } catch { toast.error("Couldn’t copy automatically — select the text and copy it."); } };
  const regen = useMutation({ mutationFn: () => post<TripDetail>(`/api/trips/${trip.id}/invite/regenerate`), onSuccess: (t) => { set(t); toast.success("New code created. The old one no longer works."); }, onError: err });
  const joining = useMutation({ mutationFn: (v: boolean) => patch<TripDetail>(`/api/trips/${trip.id}/joining`, { is_joinable: v }), onSuccess: set, onError: err });
  const remove = useMutation({ mutationFn: (uid: number) => del(`/api/trips/${trip.id}/members/${uid}`), onSuccess: () => { qc.invalidateQueries({ queryKey: ["trip", trip.id] }); qc.invalidateQueries({ queryKey: ["prefs", trip.id] }); }, onError: err });
  const leave = useMutation({ mutationFn: () => post(`/api/trips/${trip.id}/leave`), onSuccess: () => { qc.invalidateQueries({ queryKey: ["trips"] }); navigate("/app/trips"); }, onError: err });

  const share = async () => { try { await navigator.share({ title: trip.name, text: `Join our trip “${trip.name}” on MileMates AI. Code: ${trip.code}`, url: link }); } catch { /* cancelled */ } };

  return (
    <div className="mx-auto max-w-2xl space-y-6">
      <section className="card p-6 sm:p-8"><h2 className="text-xl font-semibold">Invite your group</h2>
        <p className="mt-1 text-sm text-ink-500">Friends need a MileMates account. Send them the code or the link.</p>
        <div className="mt-4 grid gap-3 sm:grid-cols-2">
          <div className="rounded-2xl bg-gradient-to-br from-lagoon-50 to-sand-100 p-5 ring-1 ring-lagoon-100"><p className="text-xs font-bold uppercase tracking-wider text-ink-500">Trip code</p><p className="mt-1 font-mono text-2xl font-bold tracking-widest">{trip.code.slice(0, 4)}-{trip.code.slice(4)}</p>
            <Button variant="secondary" className="mt-3 !py-1.5" onClick={() => copy("code", trip.code)}>{copied === "code" ? <Check className="h-4 w-4" /> : <Copy className="h-4 w-4" />}{copied === "code" ? "Copied" : "Copy code"}</Button></div>
          <div className="rounded-2xl bg-gradient-to-br from-sun-100/60 to-sand-100 p-5 ring-1 ring-sand-200"><p className="text-xs font-bold uppercase tracking-wider text-ink-500">Invite link</p><p className="mt-1 break-all text-sm font-medium">{link}</p>
            <div className="mt-3 flex flex-wrap gap-2"><Button variant="secondary" className="!py-1.5" onClick={() => copy("link", link)}>{copied === "link" ? <Check className="h-4 w-4" /> : <Link2 className="h-4 w-4" />}{copied === "link" ? "Copied" : "Copy link"}</Button>
              {typeof navigator.share === "function" && <Button variant="secondary" className="!py-1.5" onClick={share}><Share2 className="h-4 w-4" />Share</Button>}</div></div>
        </div>
        {owner && <div className="mt-4 flex flex-wrap items-center gap-3 border-t border-sand-200 pt-4">
          <label className="flex items-center gap-2 text-sm"><input type="checkbox" className="h-4 w-4 accent-lagoon-600" checked={trip.is_joinable} disabled={joining.isPending} onChange={(e) => joining.mutate(e.target.checked)} />Accepting new members</label>
          <Button variant="ghost" className="!py-1.5" loading={regen.isPending} onClick={() => { if (confirm("Create a new code? The current code and link will stop working.")) regen.mutate(); }}><RefreshCw className="h-4 w-4" />New code</Button></div>}
      </section>

      <section className="card p-6"><h2 className="text-xl font-semibold">Members ({trip.members.length})</h2>
        <ul className="mt-4 divide-y divide-sand-200">{trip.members.map((m) => (
          <li key={m.user_id} className="flex items-center gap-3 py-3"><Avatar name={m.name} />
            <div className="min-w-0 flex-1"><p className="truncate font-medium">{m.name}{m.user_id === user!.id && " (you)"}</p><p className="text-xs text-ink-500">Joined {shortDate(m.joined_at)} · {socket.online.includes(m.user_id) ? "online now" : "offline"}</p></div>
            {m.role === "owner" ? <Badge tone="teal">Organiser</Badge> : owner && <Button variant="ghost" className="!py-1.5 text-coral-700" aria-label={`Remove ${m.name}`} loading={remove.isPending && remove.variables === m.user_id}
              onClick={() => { if (confirm(`Remove ${m.name} from this trip?`)) remove.mutate(m.user_id); }}>Remove</Button>}</li>))}</ul></section>

      {!owner && (
        <section className="card p-6">
          <h2 className="text-xl font-semibold">Leave trip</h2>
          <p className="mt-1 text-sm text-ink-500">You’ll lose access to the chat and plan. You can rejoin with the code if the organiser allows.</p>
          <Button variant="secondary" className="mt-4" loading={leave.isPending} onClick={() => { if (confirm("Leave this trip?")) leave.mutate(); }}>Leave trip</Button>
        </section>
      )}
    </div>
  );
}
