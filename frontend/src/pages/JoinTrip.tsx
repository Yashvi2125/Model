import { useMutation, useQueryClient } from "@tanstack/react-query";
import { CalendarDays, MapPin, Users } from "lucide-react";
import { useEffect, useState, type FormEvent } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { Alert, Button, Input } from "../components/ui";
import { useToast } from "../context/Toast";
import { api, errorMessage, post } from "../lib/api";
import { dateRange } from "../lib/format";
import type { TripPreview } from "../lib/types";

export default function JoinTrip() {
  const [params] = useSearchParams();
  const [code, setCode] = useState(params.get("code") ?? "");
  const [preview, setPreview] = useState<TripPreview | null>(null);
  const [error, setError] = useState("");
  const navigate = useNavigate();
  const qc = useQueryClient();
  const toast = useToast();

  const lookup = useMutation({
    mutationFn: (c: string) => api<TripPreview>(`/api/trips/preview/${encodeURIComponent(c)}`),
    onSuccess: setPreview, onError: (e) => { setPreview(null); setError(errorMessage(e)); },
  });
  const join = useMutation({
    mutationFn: () => post<TripPreview>("/api/trips/join", { code: preview!.code }),
    onSuccess: (t) => { qc.invalidateQueries({ queryKey: ["trips"] }); toast.success(`You’ve joined ${t.name}.`); navigate(`/app/trips/${t.trip_id}/chat`); },
    onError: (e) => setError(errorMessage(e)),
  });

  const submit = (e: FormEvent) => {
    e.preventDefault(); setError(""); setPreview(null);
    const clean = code.replace(/[^A-Za-z0-9]/g, "");
    if (clean.length < 6) { setError("Enter the trip code you were sent (8 letters and numbers)."); return; }
    lookup.mutate(clean);
  };
  useEffect(() => { if (params.get("code")) lookup.mutate(params.get("code")!.replace(/[^A-Za-z0-9]/g, "")); /* eslint-disable-next-line */ }, []);

  return (
    <div className="mx-auto max-w-xl">
      <div><span className="eyebrow">Invite</span><h1 className="mt-3 text-3xl font-bold sm:text-4xl">Join a Trip</h1></div>
      <p className="mt-1 text-ink-500">Enter the trip code from your organiser, or open the invite link they shared.</p>
      <form onSubmit={submit} className="card mt-6 space-y-4 p-6 sm:p-8" noValidate>
        <Input label="Trip code" value={code} onChange={(e) => setCode(e.target.value.toUpperCase())} placeholder="e.g. K7MQ-4XNP"
          autoCapitalize="characters" autoComplete="off" spellCheck={false} />
        {error && <Alert>{error}</Alert>}
        <Button type="submit" loading={lookup.isPending} className="w-full">Look up trip</Button>
      </form>

      {preview && (
        <div className="card mt-6 animate-fade-up p-6 sm:p-8" aria-live="polite">
          <h2 className="text-xl font-semibold">{preview.name}</h2>
          <p className="text-sm text-ink-500">Organised by {preview.owner_name}</p>
          <ul className="mt-4 space-y-2 text-ink-700">
            <li className="flex items-center gap-2"><MapPin className="h-4 w-4 text-ink-400" aria-hidden />{preview.destination ?? "Destination undecided"}</li>
            <li className="flex items-center gap-2"><CalendarDays className="h-4 w-4 text-ink-400" aria-hidden />{dateRange(preview.start_date, preview.end_date)}</li>
            <li className="flex items-center gap-2"><Users className="h-4 w-4 text-ink-400" aria-hidden />{preview.member_count} {preview.member_count === 1 ? "person" : "people"} already in</li>
          </ul>
          {preview.already_member ? (
            <Button className="mt-5 w-full" onClick={() => navigate(`/app/trips/${preview.trip_id}/chat`)}>You’re already in — open trip</Button>
          ) : (
            <Button className="mt-5 w-full" loading={join.isPending} onClick={() => join.mutate()}>Join this trip</Button>
          )}
        </div>
      )}
    </div>
  );
}
