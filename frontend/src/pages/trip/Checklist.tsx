import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Plus, Sparkles, Trash2 } from "lucide-react";
import { useState, type FormEvent } from "react";
import { Alert, PageLoader, QueryError, Button } from "../../components/ui";
import { useToast } from "../../context/Toast";
import { useTrip } from "../../layouts/tripContext";
import { api, del, errorMessage, patch, post } from "../../lib/api";
import type { ChecklistItem } from "../../lib/types";

export default function Checklist() {
  const { trip } = useTrip();
  const qc = useQueryClient(); const toast = useToast();
  const key = ["checklist", trip.id]; const base = `/api/trips/${trip.id}/checklist`;
  const q = useQuery({ queryKey: key, queryFn: () => api<ChecklistItem[]>(base) });
  const [text, setText] = useState("");
  const refresh = () => qc.invalidateQueries({ queryKey: key });
  const toggle = useMutation({
    mutationFn: (i: ChecklistItem) => patch<ChecklistItem>(`${base}/${i.id}`, { done: !i.done }),
    onMutate: async (i) => { await qc.cancelQueries({ queryKey: key }); const prev = qc.getQueryData<ChecklistItem[]>(key);
      qc.setQueryData<ChecklistItem[]>(key, (o) => o?.map((x) => (x.id === i.id ? { ...x, done: !x.done } : x))); return { prev }; },
    onError: (e, _i, ctx) => { qc.setQueryData(key, ctx?.prev); toast.error(errorMessage(e)); }, onSettled: refresh });
  const assign = useMutation({ mutationFn: ({ id, uid }: { id: number; uid: number | null }) => patch(`${base}/${id}`, uid === null ? { clear_assignee: true } : { assignee_id: uid }), onSuccess: refresh, onError: (e) => toast.error(errorMessage(e)) });
  const add = useMutation({ mutationFn: (t: string) => post<ChecklistItem>(base, { text: t }), onSuccess: () => { setText(""); refresh(); }, onError: (e) => toast.error(errorMessage(e)) });
  const remove = useMutation({ mutationFn: (id: number) => del(`${base}/${id}`), onSuccess: refresh, onError: (e) => toast.error(errorMessage(e)) });
  const generateList = useMutation({
    mutationFn: () => post<{ added: number; provider: string; items: ChecklistItem[] }>(`${base}/generate`),
    onSuccess: (data) => {
      refresh();
      const provName = data.provider === "qwen" ? "Qwen 2.5 (Local)" : "Gemini";
      toast.success(`Added ${data.added} packing items via ${provName}!`);
    },
    onError: (e) => toast.error(errorMessage(e)),
  });
  const submit = (e: FormEvent) => { e.preventDefault(); if (text.trim()) add.mutate(text.trim()); };

  if (q.isLoading) return <PageLoader />;
  if (q.error || !q.data) return <QueryError error={q.error} retry={() => q.refetch()} />;
  const done = q.data.filter((i) => i.done).length; const total = q.data.length;
  return (
    <div className="mx-auto max-w-2xl space-y-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="text-2xl font-bold">Pre-trip checklist</h2>
          <p className="text-ink-500">Preparation tasks for the group. These are reminders, not bookings.</p>
        </div>
        <Button
          variant="secondary"
          className="!py-1.5 text-sm"
          loading={generateList.isPending}
          onClick={() => generateList.mutate()}
        >
          <Sparkles className="h-4 w-4 text-sun-500" /> AI Suggest Packing List
        </Button>
      </div>
      <Alert kind="info">TripMate AI doesn’t book hotels, flights or transport. Use this list to track what you still need to arrange yourselves.</Alert>
      <div className="card p-5">
        <div className="mb-4"><div className="flex justify-between text-sm"><span className="font-semibold">{done} of {total} done</span><span className="text-ink-500">{total ? Math.round((done / total) * 100) : 0}%</span></div>
          <div className="mt-1.5 h-2 overflow-hidden rounded-full bg-sand-200" role="progressbar" aria-valuenow={done} aria-valuemin={0} aria-valuemax={total} aria-label="Checklist progress"><div className="h-full rounded-full bg-lagoon-600 transition-all" style={{ width: `${total ? (done / total) * 100 : 0}%` }} /></div></div>
        <ul className="divide-y divide-sand-200">
          {q.data.map((i) => (
            <li key={i.id} className="flex flex-wrap items-center gap-3 py-2.5">
              <input id={`ck-${i.id}`} type="checkbox" checked={i.done} onChange={() => toggle.mutate(i)} className="h-5 w-5 rounded accent-lagoon-600" />
              <label htmlFor={`ck-${i.id}`} className={`min-w-0 flex-1 cursor-pointer break-words ${i.done ? "text-ink-400 line-through" : ""}`}>{i.text}</label>
              <label className="sr-only" htmlFor={`as-${i.id}`}>Assign “{i.text}”</label>
              <select id={`as-${i.id}`} className="input !w-auto !py-1.5 text-sm" value={i.assignee_id ?? ""} onChange={(e) => assign.mutate({ id: i.id, uid: e.target.value ? Number(e.target.value) : null })}>
                <option value="">Unassigned</option>{trip.members.map((m) => <option key={m.user_id} value={m.user_id}>{m.name}</option>)}</select>
              <button className="rounded-lg p-2 min-h-[44px] min-w-[44px] flex items-center justify-center text-ink-400 hover:bg-coral-100 hover:text-coral-700" aria-label={`Delete “${i.text}”`} onClick={() => remove.mutate(i.id)}><Trash2 className="h-4 w-4" /></button>
            </li>))}
          {total === 0 && <li className="py-6 text-center text-ink-500">Nothing on the list yet.</li>}
        </ul>
        <form onSubmit={submit} className="mt-4 flex gap-2"><label htmlFor="new-item" className="sr-only">New checklist item</label>
          <input id="new-item" className="input" value={text} onChange={(e) => setText(e.target.value)} placeholder="Add a task, e.g. Book train tickets" maxLength={300} />
          <Button type="submit" loading={add.isPending} disabled={!text.trim()}><Plus className="h-4 w-4" />Add</Button></form>
      </div>
    </div>
  );
}
