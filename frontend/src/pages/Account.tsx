import { useQuery } from "@tanstack/react-query";
import { CheckCircle2, CircleX, LogOut, Send } from "lucide-react";
import { useState, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import { Alert, Avatar, Button, Input } from "../components/ui";
import { useAuth } from "../context/AuthContext";
import { useToast } from "../context/Toast";
import { ApiError, api, del, errorMessage, patch, post } from "../lib/api";
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

  // Telegram link state
  const [linkCode, setLinkCode] = useState<string | null>(null);
  const [botUsername, setBotUsername] = useState("Tripmate_planner_bot");
  const [generatingCode, setGeneratingCode] = useState(false);
  const [unlinking, setUnlinking] = useState(false);

  const handleGenerateCode = async () => {
    setGeneratingCode(true);
    try {
      const res = await post<{ code: string; expires_at: string; bot_username: string }>("/api/users/me/telegram-link-code");
      setLinkCode(res.code);
      if (res.bot_username) setBotUsername(res.bot_username);
    } catch (err) {
      toast.error(errorMessage(err));
    } finally {
      setGeneratingCode(false);
    }
  };

  const handleDisconnectTelegram = async () => {
    setUnlinking(true);
    try {
      const updated = await del<User>("/api/users/me/telegram-link");
      if (updated) setUser(updated);
      setLinkCode(null);
      toast.success("Telegram account disconnected.");
    } catch (err) {
      toast.error(errorMessage(err));
    } finally {
      setUnlinking(false);
    }
  };

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
      <div><span className="eyebrow">Account</span><h1 className="mt-3 text-3xl font-bold sm:text-4xl">Profile</h1></div>
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

      {/* Telegram Account Linking Card */}
      <div className="card mt-6 p-6">
        <div className="flex items-center justify-between gap-4">
          <div className="flex items-center gap-3">
            <div className="flex h-10 w-10 items-center justify-center rounded-full bg-sky-100 text-sky-600">
              <Send className="h-5 w-5" />
            </div>
            <div>
              <h2 className="text-lg font-semibold">Telegram Integration</h2>
              <p className="text-sm text-ink-500">
                Connect your account to plan trips via Telegram groups and direct messages.
              </p>
            </div>
          </div>
        </div>

        {user?.telegram_user_id ? (
          <div className="mt-4 flex flex-col sm:flex-row sm:items-center justify-between gap-4 rounded-lg bg-lagoon-50 border border-lagoon-200 p-4">
            <div>
              <p className="text-sm font-semibold text-lagoon-900">
                Connected to Telegram
              </p>
              <p className="text-xs text-lagoon-700 mt-0.5">
                {user.telegram_username ? `@${user.telegram_username}` : `Telegram ID: ${user.telegram_user_id}`}
              </p>
            </div>
            <Button
              variant="secondary"
              loading={unlinking}
              onClick={handleDisconnectTelegram}
              className="text-coral-600 hover:text-coral-700"
            >
              Disconnect
            </Button>
          </div>
        ) : (
          <div className="mt-4 space-y-4">
            {!linkCode ? (
              <div>
                <p className="text-sm text-ink-600 mb-3">
                  Link your account to seamlessly chat with the bot in your trip groups and have your messages sync with this dashboard.
                </p>
                <Button onClick={handleGenerateCode} loading={generatingCode}>
                  Connect Telegram Account
                </Button>
              </div>
            ) : (
              <div className="rounded-lg border border-sky-200 bg-sky-50 p-4 space-y-3">
                <p className="text-sm font-medium text-sky-900">
                  Step 1: Open a private chat with{" "}
                  <a
                    href={`https://t.me/${botUsername}`}
                    target="_blank"
                    rel="noreferrer"
                    className="underline font-semibold"
                  >
                    @{botUsername}
                  </a>
                </p>
                <p className="text-sm font-medium text-sky-900">
                  Step 2: Send this command to the bot:
                </p>
                <div className="flex items-center gap-2">
                  <code className="flex-1 rounded bg-white px-3 py-2 font-mono text-sm border border-sky-300 font-bold select-all">
                    /link {linkCode}
                  </code>
                  <Button
                    variant="secondary"
                    onClick={() => {
                      navigator.clipboard.writeText(`/link ${linkCode}`);
                      toast.success("Command copied to clipboard!");
                    }}
                  >
                    Copy
                  </Button>
                </div>
                <p className="text-xs text-sky-700">
                  ⏳ This code expires in 10 minutes and can only be used once. Send it in a direct message, not in a group.
                </p>
              </div>
            )}
          </div>
        )}
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
      <div><span className="eyebrow">Account</span><h1 className="mt-3 text-3xl font-bold sm:text-4xl">Settings</h1></div>
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
