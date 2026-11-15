import { useQuery } from "@tanstack/react-query";
import { CheckCircle2, CircleX, LogOut } from "lucide-react";
import { useState, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import { Alert, Avatar, Button, Input } from "../components/ui";
import { useAuth } from "../context/AuthContext";
import { useToast } from "../context/Toast";
import { ApiError, api, errorMessage, patch, post } from "../lib/api";
import { shortDate } from "../lib/format";
import type { AIStatus, User } from "../lib/types";
import { emailValid, passwordChecks, passwordValid } from "../lib/validation";
import { PasswordInput } from "./AuthPages";

export function Profile() {
  const { user, setUser, logout } = useAuth();
  const toast = useToast();
  const navigate = useNavigate();
  const [name, setName] = useState(user!.name);
  const [email, setEmail] = useState(user!.email);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);

  const save = async (e: FormEvent) => {
    e.preventDefault();
    const er: Record<string, string> = {};
    if (name.trim().length < 2) er.name = "Enter your full name.";
    if (!emailValid(email)) er.email = "Enter a valid email address.";
    setErrors(er);
    if (Object.keys(er).length) return;
    setBusy(true);
    try { setUser(await patch<User>("/api/users/me", { name: name.trim(), email: email.trim() })); toast.success("Profile saved."); }
    catch (err) { setErrors(err instanceof ApiError && err.fields ? { ...err.fields, form: err.message } : { form: errorMessage(err) }); }
    finally { setBusy(false); }
  };

  return (
    <div className="mx-auto max-w-2xl">
      <h1 className="text-3xl font-bold">Profile</h1>
      <div className="card mt-6 p-6">
        <div className="mb-6 flex items-center gap-4"><Avatar name={user!.name} size="lg" />
          <div><p className="text-lg font-semibold">{user!.name}</p><p className="text-sm text-ink-500">Member since {shortDate(user!.created_at)}</p></div></div>
        <form onSubmit={save} noValidate className="space-y-4">
          {errors.form && <Alert>{errors.form}</Alert>}
          <Input label="Full name" value={name} onChange={(e) => setName(e.target.value)} error={errors.name} autoComplete="name" />
          <Input label="Email" type="email" value={email} onChange={(e) => setEmail(e.target.value)} error={errors.email} autoComplete="email" />
          <Button type="submit" loading={busy}>Save changes</Button>
        </form>
      </div>
      <div className="card mt-6 flex items-center justify-between gap-4 p-6">
        <div><h2 className="text-lg font-semibold">Log out</h2><p className="text-sm text-ink-500">Ends this session on this device.</p></div>
        <Button variant="secondary" onClick={async () => { await logout(); navigate("/", { replace: true }); }}><LogOut className="h-4 w-4" />Log out</Button>
      </div>
    </div>
  );
}

export function Settings() {
  const toast = useToast();
  const [cur, setCur] = useState(""); const [next, setNext] = useState(""); const [conf, setConf] = useState("");
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const ai = useQuery({ queryKey: ["ai-status"], queryFn: () => api<AIStatus>("/api/ai/status") });

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    const er: Record<string, string> = {};
    if (!cur) er.cur = "Enter your current password.";
    if (!passwordValid(next)) er.next = "New password doesn’t meet the requirements below.";
    if (conf !== next) er.conf = "Passwords don’t match.";
    setErrors(er);
    if (Object.keys(er).length) return;
    setBusy(true);
    try { await post("/api/users/me/password", { current_password: cur, new_password: next }); setCur(""); setNext(""); setConf(""); toast.success("Password changed. Other devices were signed out."); }
    catch (err) { setErrors({ form: errorMessage(err) }); }
    finally { setBusy(false); }
  };

  return (
    <div className="mx-auto max-w-2xl">
      <h1 className="text-3xl font-bold">Settings</h1>
      <form onSubmit={submit} noValidate className="card mt-6 space-y-4 p-6">
        <h2 className="text-lg font-semibold">Change password</h2>
        {errors.form && <Alert>{errors.form}</Alert>}
        <PasswordInput label="Current password" autoComplete="current-password" value={cur} onChange={setCur} error={errors.cur} />
        <PasswordInput label="New password" autoComplete="new-password" value={next} onChange={setNext} error={errors.next} />
        <ul className="-mt-2 flex flex-wrap gap-x-4 text-xs text-ink-500">{passwordChecks(next).map((c) => <li key={c.id} className={c.ok ? "text-lagoon-700" : ""}>{c.ok ? "✓" : "•"} {c.label}</li>)}</ul>
        <PasswordInput label="Confirm new password" autoComplete="new-password" value={conf} onChange={setConf} error={errors.conf} />
        <Button type="submit" loading={busy}>Update password</Button>
      </form>

      <div className="card mt-6 p-6">
        <h2 className="text-lg font-semibold">AI services on this server</h2>
        <p className="mt-1 text-sm text-ink-500">These are configured by whoever runs the app, in the <code>.env</code> file. API keys are never shown in the browser.</p>
        {ai.data && (
          <ul className="mt-4 space-y-2 text-sm">
            {[["Gemini (chat, conflicts, itineraries)", ai.data.gemini_configured, "Add GEMINI_API_KEY"], ["Tavily (live web research)", ai.data.tavily_configured, "Add TAVILY_API_KEY — itineraries still work without it"]].map(([l, ok, fix]) => (
              <li key={String(l)} className="flex items-start gap-2">{ok ? <CheckCircle2 className="mt-0.5 h-4 w-4 text-lagoon-600" /> : <CircleX className="mt-0.5 h-4 w-4 text-coral-500" />}
                <span><span className="font-medium">{l}</span> — {ok ? "configured" : String(fix)}</span></li>))}
            <li className="text-ink-500">Model: {ai.data.model}</li>
          </ul>)}
      </div>
    </div>
  );
}
