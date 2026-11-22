import { Check, Eye, EyeOff } from "lucide-react";
import { useState, type FormEvent, type ReactNode } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import { Logo } from "../components/Logo";
import { Alert, Button, Input } from "../components/ui";
import { useAuth } from "../context/AuthContext";
import { ApiError, errorMessage } from "../lib/api";
import { emailValid, passwordChecks, passwordValid } from "../lib/validation";

function Frame({ title, subtitle, children, footer }: { title: string; subtitle: string; children: ReactNode; footer: ReactNode }) {
  return (
    <div className="grid min-h-screen lg:grid-cols-[1fr_1.05fr]">
      <div className="flex flex-col px-4 py-8 sm:px-12">
        <Logo />
        <div className="mx-auto flex w-full max-w-md flex-1 flex-col justify-center py-10">
          <h1 className="text-3xl font-bold">{title}</h1>
          <p className="mt-2 text-ink-500">{subtitle}</p>
          <div className="mt-8">{children}</div>
          <p className="mt-6 text-sm text-ink-500">{footer}</p>
        </div>
      </div>
      <div className="relative hidden overflow-hidden bg-lagoon-800 lg:block" aria-hidden>
        <svg viewBox="0 0 600 800" className="absolute inset-0 h-full w-full" preserveAspectRatio="xMidYMid slice">
          <rect width="600" height="800" fill="#0B4D4B" />
          <circle cx="440" cy="190" r="70" fill="#E9A23B" />
          <path d="M0 520 L130 360 L230 470 L350 300 L470 460 L600 380 V800 H0Z" fill="#0C625F" />
          <path d="M0 610 L110 500 L220 590 L330 480 L450 590 L600 520 V800 H0Z" fill="#0F7C77" />
          <path d="M0 700 Q150 650 300 700 T600 690 V800 H0Z" fill="#14958F" />
          <path d="M70 740 C160 600 250 690 330 560 S470 520 520 430" fill="none" stroke="#FBF8F2" strokeWidth="4" strokeLinecap="round" strokeDasharray="1 14" />
          {[[70, 740, "A"], [330, 560, "R"], [520, 430, "S"]].map(([x, y, t]) => (
            <g key={String(t)}><circle cx={x as number} cy={y as number} r="20" fill="#FBF8F2" /><text x={x as number} y={(y as number) + 6} textAnchor="middle" fontSize="18" fontWeight="700" fill="#0B4D4B">{t}</text></g>))}
        </svg>
        <div className="absolute bottom-12 left-12 right-12 text-white">
          <p className="font-display text-3xl font-bold leading-tight">Everyone’s ideas.<br />One plan that works.</p>
        </div>
      </div>
    </div>
  );
}

function PasswordInput({ label, value, onChange, error, autoComplete, hint }:
  { label: string; value: string; onChange: (v: string) => void; error?: string; autoComplete: string; hint?: string }) {
  const [show, setShow] = useState(false);
  return (
    <div className="relative">
      <Input label={label} type={show ? "text" : "password"} value={value} onChange={(e) => onChange(e.target.value)}
        error={error} hint={hint} autoComplete={autoComplete} className="pr-11" />
      <button type="button" onClick={() => setShow((s) => !s)} aria-label={show ? "Hide password" : "Show password"} aria-pressed={show}
        className="absolute right-1 top-[28px] rounded-lg p-2 text-ink-500 hover:bg-sand-100 min-h-[44px] min-w-[44px] flex items-center justify-center">
        {show ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
      </button>
    </div>
  );
}
export { PasswordInput };

export function Login() {
  const { login } = useAuth();
  const navigate = useNavigate();
  const loc = useLocation() as { state?: { from?: string; expired?: boolean } };
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [remember, setRemember] = useState(false);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [formError, setFormError] = useState("");
  const [busy, setBusy] = useState(false);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    const er: Record<string, string> = {};
    if (!emailValid(email)) er.email = "Enter a valid email address.";
    if (!password) er.password = "Enter your password.";
    setErrors(er); setFormError("");
    if (Object.keys(er).length) return;
    setBusy(true);
    try { await login(email.trim(), password, remember); navigate(loc.state?.from ?? "/app", { replace: true }); }
    catch (err) { setFormError(errorMessage(err)); }
    finally { setBusy(false); }
  };

  return (
    <Frame title="Welcome back" subtitle="Log in to pick up your group’s plans where you left them."
      footer={<>New to TripMate? <Link className="font-semibold text-lagoon-700 underline" to="/register">Create an account</Link></>}>
      <form onSubmit={submit} noValidate className="space-y-4">
        {loc.state?.expired && <Alert kind="info">Your session ended. Please log in again.</Alert>}
        {formError && <Alert>{formError}</Alert>}
        <Input label="Email" type="email" autoComplete="email" value={email} onChange={(e) => setEmail(e.target.value)} error={errors.email} />
        <PasswordInput label="Password" autoComplete="current-password" value={password} onChange={setPassword} error={errors.password} />
        <label className="flex items-center gap-2 text-sm text-ink-700">
          <input type="checkbox" checked={remember} onChange={(e) => setRemember(e.target.checked)} className="h-4 w-4 rounded border-sand-300 accent-lagoon-600" />
          Keep me logged in on this device for 30 days
        </label>
        <Button type="submit" loading={busy} className="w-full">{busy ? "Logging in…" : "Log in"}</Button>
        <p className="text-xs text-ink-500">Forgot your password? Password reset by email isn’t available yet — you can change it from Settings while logged in.</p>
      </form>
    </Frame>
  );
}

export function Register() {
  const { register } = useAuth();
  const navigate = useNavigate();
  const [v, setV] = useState({ name: "", email: "", password: "", confirm: "" });
  const [terms, setTerms] = useState(false);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [formError, setFormError] = useState("");
  const [busy, setBusy] = useState(false);
  const set = (k: keyof typeof v) => (val: string) => setV((s) => ({ ...s, [k]: val }));

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    const er: Record<string, string> = {};
    if (v.name.trim().length < 2) er.name = "Enter your full name.";
    if (!emailValid(v.email)) er.email = "Enter a valid email address.";
    if (!passwordValid(v.password)) er.password = "Password doesn’t meet the requirements below.";
    if (v.confirm !== v.password) er.confirm = "Passwords don’t match.";
    if (!terms) er.terms = "Please accept the terms to continue.";
    setErrors(er); setFormError("");
    if (Object.keys(er).length) return;
    setBusy(true);
    try {
      await register({ name: v.name.trim(), email: v.email.trim(), password: v.password, confirm_password: v.confirm, accept_terms: terms });
      navigate("/app", { replace: true });
    } catch (err) {
      if (err instanceof ApiError && Object.keys(err.fields).length) setErrors(err.fields);
      setFormError(errorMessage(err));
    } finally { setBusy(false); }
  };

  return (
    <Frame title="Create your account" subtitle="It takes a minute. Then start a trip and invite your group."
      footer={<>Already have an account? <Link className="font-semibold text-lagoon-700 underline" to="/login">Log in</Link></>}>
      <form onSubmit={submit} noValidate className="space-y-4">
        {formError && <Alert>{formError}</Alert>}
        <Input label="Full name" autoComplete="name" value={v.name} onChange={(e) => set("name")(e.target.value)} error={errors.name} />
        <Input label="Email" type="email" autoComplete="email" value={v.email} onChange={(e) => set("email")(e.target.value)} error={errors.email} />
        <PasswordInput label="Password" autoComplete="new-password" value={v.password} onChange={set("password")} error={errors.password} />
        <ul className="-mt-2 flex flex-wrap gap-x-4 gap-y-1 text-xs" aria-label="Password requirements">
          {passwordChecks(v.password).map((c) => (
            <li key={c.id} className={`flex items-center gap-1 ${c.ok ? "text-lagoon-700" : "text-ink-500"}`}>
              <Check className={`h-3.5 w-3.5 ${c.ok ? "" : "opacity-30"}`} aria-hidden />{c.label}<span className="sr-only">{c.ok ? " (met)" : " (not met yet)"}</span>
            </li>))}
        </ul>
        <PasswordInput label="Confirm password" autoComplete="new-password" value={v.confirm} onChange={set("confirm")} error={errors.confirm} />
        <div>
          <label className="flex items-start gap-2 text-sm text-ink-700">
            <input type="checkbox" checked={terms} onChange={(e) => setTerms(e.target.checked)} className="mt-0.5 h-4 w-4 rounded border-sand-300 accent-lagoon-600" />
            <span>I understand this is a student project and that AI-generated plans are suggestions that need checking before I book anything.</span>
          </label>
          {errors.terms && <p role="alert" className="mt-1 text-sm text-coral-700">{errors.terms}</p>}
        </div>
        <Button type="submit" loading={busy} className="w-full">{busy ? "Creating account…" : "Create account"}</Button>
      </form>
    </Frame>
  );
}
