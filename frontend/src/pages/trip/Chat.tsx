import { useQuery, useQueryClient } from "@tanstack/react-query";
import { AtSign, ChevronDown, CircleAlert, RotateCw, Send, Sparkles } from "lucide-react";
import { Fragment, useLayoutEffect, useRef, useState, type KeyboardEvent } from "react";
import { Link } from "react-router-dom";
import { Markdown } from "../../components/Markdown";
import { Avatar, Badge, PageLoader, QueryError, Spinner } from "../../components/ui";
import { useTrip } from "../../layouts/tripContext";
import { api, errorMessage, post } from "../../lib/api";
import { dayLabel, timeOf } from "../../lib/format";
import type { ChatMessage, ConflictsResult, Itinerary, PreferencesOverview } from "../../lib/types";
import { useAuth } from "../../context/AuthContext";

interface Outgoing { tempId: number; content: string; status: "sending" | "failed"; error?: string }

function PlanningPanel({ tripId }: { tripId: number }) {
  const { trip, socket } = useTrip();
  const prefs = useQuery({ queryKey: ["prefs", tripId], queryFn: () => api<PreferencesOverview>(`/api/trips/${tripId}/preferences`) });
  const conflicts = useQuery({ queryKey: ["conflicts", tripId], queryFn: () => api<ConflictsResult>(`/api/trips/${tripId}/conflicts`) });
  const itin = useQuery({ queryKey: ["itinerary", tripId], queryFn: () => api<Itinerary | null>(`/api/trips/${tripId}/itinerary`) });
  const filled = prefs.data?.members.filter((m) => m.missing.length < 4).length ?? 0;
  const open = conflicts.data?.conflicts.filter((c) => c.status === "open").length ?? 0;
  const link = "flex items-center justify-between rounded-lg px-3 py-2 text-sm hover:bg-sand-100";
  return (
    <div className="space-y-4">
      <section className="card p-4">
        <h2 className="text-sm font-semibold">Members ({trip.members.length})</h2>
        <ul className="mt-3 space-y-2.5">
          {trip.members.map((m) => (
            <li key={m.user_id} className="flex items-center gap-2.5">
              <span className="relative"><Avatar name={m.name} size="sm" />
                <span className={`absolute -bottom-0.5 -right-0.5 h-2.5 w-2.5 rounded-full border-2 border-white ${socket.online.includes(m.user_id) ? "bg-emerald-500" : "bg-sand-300"}`}>
                  <span className="sr-only">{socket.online.includes(m.user_id) ? "online" : "offline"}</span></span></span>
              <span className="min-w-0 flex-1 truncate text-sm">{m.name}</span>
              {m.role === "owner" && <Badge tone="teal">Organiser</Badge>}
            </li>))}
        </ul>
      </section>
      <section className="card p-2">
        <h2 className="px-3 pt-2 text-sm font-semibold">Planning status</h2>
        <ul className="mt-1">
          <li><Link to="../preferences" className={link}><span>Preferences shared</span><span className="font-semibold">{prefs.data ? `${filled}/${trip.members.length}` : "…"}</span></Link></li>
          {!!prefs.data?.pending_suggestions_total && <li><Link to="../preferences" className={link}><span>AI suggestions to review</span><Badge tone="amber">{prefs.data.pending_suggestions_total}</Badge></Link></li>}
          <li><Link to="../conflicts" className={link}><span>Open disagreements</span><span className="font-semibold">{conflicts.data ? open : "…"}</span></Link></li>
          <li><Link to="../itinerary" className={link}><span>Itinerary</span>
            <span className="font-semibold">{itin.data ? (itin.data.status === "running" ? "Planning…" : itin.data.status === "succeeded" ? `v${itin.data.version} ready` : "Failed") : "Not yet"}</span></Link></li>
        </ul>
      </section>
    </div>
  );
}

function Bubble({ m, mine, tripPath }: { m: ChatMessage; mine: boolean; tripPath: string }) {
  if (m.kind === "system")
    return <div className="my-2 text-center text-xs text-ink-500"><span className="rounded-full bg-sand-100 px-3 py-1">{m.content}</span></div>;
  const ai = m.kind === "ai";
  const err = ai && m.meta.error === true;
  const isTg = m.channel === "telegram" || m.meta?.channel === "telegram";
  return (
    <div className={`flex items-end gap-2.5 ${mine ? "flex-row-reverse" : ""}`}>
      {!mine && (ai ? <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-lagoon-600 text-white"><Sparkles className="h-4 w-4" aria-hidden /></span> : <Avatar name={m.sender_name} />)}
      <div className={`max-w-[82%] rounded-2xl px-4 py-2.5 ${mine ? "rounded-br-md bg-lagoon-600 text-white" : err ? "rounded-bl-md border border-coral-500/30 bg-coral-100 text-coral-700" : ai ? "rounded-bl-md border border-lagoon-200 bg-lagoon-50" : "rounded-bl-md border border-sand-200 bg-white"}`}>
        <p className={`mb-0.5 flex items-center flex-wrap gap-1 text-xs font-semibold ${mine ? "text-lagoon-100" : "text-ink-500"}`}>
          <span>{mine ? "You" : m.sender_name}</span>
          {isTg && <span className="inline-flex items-center px-1.5 py-0.2 rounded text-[10px] font-medium bg-sky-100 text-sky-800 border border-sky-200">Telegram</span>}
          <span>·</span>
          <time dateTime={m.created_at}>{timeOf(m.created_at)}</time>
        </p>
        {ai ? <Markdown>{m.content}</Markdown> : <p className="whitespace-pre-wrap break-words text-[15px]">{m.content}</p>}
        {ai && m.meta.suggestion_id != null && <Link to={`${tripPath}/preferences`} className="mt-1.5 inline-flex rounded-full bg-white px-2.5 py-1 text-xs font-semibold text-lagoon-800 underline">Review the preferences I noted</Link>}
      </div>
    </div>
  );
}

export default function Chat() {
  const { trip, socket } = useTrip();
  const { user } = useAuth();
  const qc = useQueryClient();
  const key = ["messages", trip.id];
  const q = useQuery({ queryKey: key, queryFn: () => api<ChatMessage[]>(`/api/trips/${trip.id}/messages?limit=200`),
    refetchInterval: socket.status === "open" ? false : 5000 });
  const [text, setText] = useState("");
  const [out, setOut] = useState<Outgoing[]>([]);
  const [panel, setPanel] = useState(false);
  const endRef = useRef<HTMLDivElement>(null);
  const boxRef = useRef<HTMLDivElement>(null);
  const stick = useRef(true);
  const taRef = useRef<HTMLTextAreaElement>(null);

  const onScroll = () => { const b = boxRef.current!; stick.current = b.scrollHeight - b.scrollTop - b.clientHeight < 120; };
  useLayoutEffect(() => { if (stick.current) endRef.current?.scrollIntoView({ block: "end" }); }, [q.data?.length, out.length, socket.aiThinking]);

  const send = async (content: string, tempId = Date.now()) => {
    stick.current = true;
    setOut((o) => [...o.filter((x) => x.tempId !== tempId), { tempId, content, status: "sending" }]);
    try {
      const m = await post<ChatMessage>(`/api/trips/${trip.id}/messages`, { content });
      qc.setQueryData<ChatMessage[]>(key, (old) => (old ?? []).some((x) => x.id === m.id) ? old : [...(old ?? []), m]);
      setOut((o) => o.filter((x) => x.tempId !== tempId));
    } catch (e) {
      setOut((o) => o.map((x) => (x.tempId === tempId ? { ...x, status: "failed", error: errorMessage(e) } : x)));
    }
  };
  const submit = () => { const c = text.trim(); if (!c) return; setText(""); void send(c); };
  const onKey = (e: KeyboardEvent<HTMLTextAreaElement>) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); submit(); } };
  const insertAi = () => { setText((t) => (t.includes("@ai") ? t : `@ai ${t}`)); taRef.current?.focus(); };
  const dest = trip.destination ?? "our trip";
  const starters = [`@ai What are the best things to do in ${dest}?`, "@ai I prefer ", "@ai Do we have any disagreements so far?"];

  const msgs = q.data ?? [];
  let lastDay = "";
  return (
    <div className="grid gap-5 lg:grid-cols-[1fr_17rem]">
      <section className="card flex h-[calc(100dvh-13rem)] sm:h-[calc(100dvh-15rem)] min-h-[26rem] flex-col overflow-hidden" aria-label="Group chat">
        <div className="no-print flex items-center justify-between border-b border-sand-200 px-4 py-2.5 lg:hidden">
          <button className="flex items-center gap-1.5 text-sm font-semibold text-lagoon-800 min-h-[44px]" aria-expanded={panel} onClick={() => setPanel((p) => !p)}>
            Group info <ChevronDown className={`h-4 w-4 transition-transform ${panel ? "rotate-180" : ""}`} /></button>
          <span className="text-xs text-ink-500">{socket.online.length} online</span>
        </div>
        {panel && <div className="max-h-72 overflow-y-auto border-b border-sand-200 bg-sand-50 p-3 lg:hidden"><PlanningPanel tripId={trip.id} /></div>}

        <div ref={boxRef} onScroll={onScroll} className="flex-1 space-y-3 overflow-y-auto px-4 py-4" role="log" aria-live="polite" aria-label="Messages">
          {q.isLoading ? <PageLoader label="Loading messages…" /> : q.error ? <QueryError error={q.error} retry={() => q.refetch()} /> :
            msgs.length === 0 && out.length === 0 ? (
              <div className="flex h-full flex-col items-center justify-center text-center text-ink-500"><Sparkles className="mb-3 h-8 w-8 text-lagoon-600" />
                <p className="font-semibold text-ink-900">No messages yet</p><p className="max-w-xs text-sm">Say hello, share what you’d love to do, or mention @ai to ask TripMate AI.</p></div>) :
              msgs.map((m) => {
                const d = dayLabel(m.created_at); const show = d !== lastDay; lastDay = d;
                return <Fragment key={m.id}>{show && <p className="py-1 text-center text-xs font-semibold text-ink-400">{d}</p>}
                  <Bubble m={m} mine={m.kind === "user" && m.sender_id === user!.id} tripPath={`/app/trips/${trip.id}`} /></Fragment>;
              })}
          {out.map((o) => (
            <div key={o.tempId} className="flex flex-row-reverse items-end gap-2.5">
              <div className={`max-w-[82%] rounded-2xl rounded-br-md px-4 py-2.5 ${o.status === "failed" ? "border border-coral-500/40 bg-coral-100" : "bg-lagoon-600/70 text-white"}`}>
                <p className={`whitespace-pre-wrap break-words text-[15px] ${o.status === "failed" ? "text-ink-900" : ""}`}>{o.content}</p>
                {o.status === "sending" ? <p className="mt-1 flex items-center gap-1.5 text-xs"><Spinner className="h-3 w-3" />Sending…</p> :
                  <p className="mt-1 flex flex-wrap items-center gap-2 text-xs text-coral-700" role="alert"><CircleAlert className="h-3.5 w-3.5" />{o.error}
                    <button className="inline-flex items-center gap-1 font-semibold underline" onClick={() => send(o.content, o.tempId)}><RotateCw className="h-3 w-3" />Retry</button>
                    <button className="underline" onClick={() => setOut((x) => x.filter((y) => y.tempId !== o.tempId))}>Discard</button></p>}
              </div>
            </div>))}
          {socket.aiThinking && <div className="flex items-center gap-2 text-sm text-lagoon-800" role="status"><Spinner />{socket.aiLabel || "TripMate AI is thinking…"}</div>}
          <div ref={endRef} />
        </div>

        <div className="no-print border-t border-sand-200 p-3 bg-white">
          <div className="mb-2 flex flex-wrap gap-1.5">{starters.map((s) => <button key={s} className="chip !py-1 text-xs" onClick={() => { setText(s); taRef.current?.focus(); }}>{s.length > 38 ? s.slice(0, 36) + "…" : s}</button>)}</div>
          <div className="flex items-end gap-2">
            <button type="button" className="btn-secondary !p-0 h-11 w-11 shrink-0 flex items-center justify-center rounded-xl" onClick={insertAi} aria-label="Mention TripMate AI" title="Mention TripMate AI"><AtSign className="h-5 w-5" /></button>
            <label className="sr-only" htmlFor="chat-input">Message</label>
            <textarea id="chat-input" ref={taRef} value={text} onChange={(e) => setText(e.target.value)} onKeyDown={onKey} rows={1} maxLength={4000}
              placeholder="Message your group — mention @ai to talk to TripMate AI" className="input max-h-36 min-h-[44px] resize-none" />
            <button type="button" onClick={submit} disabled={!text.trim()} className="btn-primary !p-0 h-11 w-11 shrink-0 flex items-center justify-center rounded-xl disabled:opacity-40" aria-label="Send message"><Send className="h-5 w-5" /></button>
          </div>
          <p className="mt-1.5 text-xs text-ink-400">Enter to send · Shift+Enter for a new line. Only messages that mention @ai get a reply; other messages may be scanned for preferences you’ll be asked to confirm.</p>
        </div>
      </section>
      <aside className="no-print hidden lg:block"><PlanningPanel tripId={trip.id} /></aside>
    </div>
  );
}
