import { Check, Eye, EyeOff } from "lucide-react";
import { useState, type FormEvent, type ReactNode } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import { Logo } from "../components/Logo";
import { Alert, Button, Input } from "../components/ui";
import { useAuth } from "../context/AuthContext";
import { ApiError, errorMessage } from "../lib/api";
import { emailValid, passwordChecks, passwordValid } from "../lib/validation";

function Frame({ title, subtitle, children, footer, wide = false }: { title: string; subtitle: string; children: ReactNode; footer: ReactNode; wide?: boolean }) {
  return (
    <div className="grid min-h-dvh md:h-dvh md:overflow-hidden lg:grid-cols-[1fr_1fr]">
      <div className="relative flex min-h-0 flex-col px-4 py-5 sm:px-10">
        <div className="pointer-events-none absolute inset-0 bg-grid mask-fade-b opacity-60" aria-hidden />
        <div className="relative"><Logo /></div>
        <div className={`relative mx-auto flex min-h-0 w-full flex-1 flex-col justify-center py-4 ${wide ? "max-w-xl" : "max-w-md"}`}>
          <div className="card animate-fade-up p-6 sm:p-7">
            <h1 className="text-2xl font-bold sm:text-3xl">{title}</h1>
            <p className="mt-1.5 text-sm text-ink-500 sm:text-[15px]">{subtitle}</p>
            <div className="mt-5">{children}</div>
          </div>
          <p className="mt-4 text-center text-sm text-ink-500">{footer}</p>
        </div>
      </div>
      <AuthArt />
    </div>
  );
}

function AuthArt() {
  return (
    <div className="hidden min-h-0 p-3 lg:block" aria-hidden>
      <div className="relative h-full overflow-hidden rounded-[2rem] bg-gradient-to-b from-lagoon-100 via-sand-100 to-sun-100 shadow-card ring-1 ring-white">
        <div className="absolute inset-0 bg-dots-dark opacity-60" />
        <div className="absolute right-14 top-28 h-24 w-24 rounded-full bg-sun-500" style={{ boxShadow: "0 0 70px 22px rgba(233,162,59,.35)" }} />
        <div className="absolute left-12 top-[17rem] h-8 w-28 animate-float rounded-full bg-white/80 blur-[2px]" />
        <div className="absolute right-44 top-[15rem] h-6 w-20 animate-float-slow rounded-full bg-white/70 blur-[2px]" />

        <div className="absolute inset-x-10 top-10">
          <span className="eyebrow">Plan together</span>
          <p className="mt-4 font-display text-4xl font-bold leading-[1.08] text-ink-900 xl:text-5xl">Everyone’s ideas.<br /><span className="text-gradient">One plan that works.</span></p>
        </div>

        <svg viewBox="0 0 600 440" className="absolute inset-x-0 bottom-0 h-[56%] w-full" preserveAspectRatio="xMidYMax slice">
          <path d="M0 200 L90 120 L170 180 L270 70 L370 170 L450 110 L600 190 V440 H0Z" fill="#B7E0DA" />
          <path d="M0 270 L100 190 L190 250 L290 160 L400 260 L490 200 L600 260 V440 H0Z" fill="#6FBFB7" />
          <path d="M0 340 Q150 290 300 340 T600 330 V440 H0Z" fill="#14958F" />
          <path d="M0 395 Q160 360 320 395 T600 390 V440 H0Z" fill="#0F7C77" />
          <path className="animate-dash" d="M60 418 C140 340 230 390 300 320 S440 270 520 215" fill="none" stroke="#FBF8F2" strokeWidth="4.5" strokeLinecap="round" strokeDasharray="2 13" />
          {([[60, 418, "A", "#E9A23B"], [300, 320, "R", "#D9644A"], [520, 215, "S", "#14233D"]] as const).map(([x, y, t, c]) => (
            <g key={t}>
              <ellipse cx={x} cy={y + 5} rx="13" ry="4.5" fill="#0B4D4B" opacity=".3" />
              <path d={`M${x} ${y + 3} l-15 -29 a19 19 0 1 1 30 0z`} fill={c} />
              <text x={x} y={y - 24} textAnchor="middle" fontSize="15" fontWeight="700" fill="#fff">{t}</text>
            </g>))}
        </svg>

        <div className="absolute bottom-[34%] left-8 w-64 animate-float rounded-3xl border border-white/80 bg-white/90 p-4 shadow-float backdrop-blur-xl">
          <div className="flex items-center gap-2.5"><span className="flex h-7 w-7 items-center justify-center rounded-full bg-gradient-to-br from-sun-100 to-[#F8D99B] text-xs font-bold text-sun-700">A</span><p className="text-xs font-semibold text-ink-500">Asha · Group chat</p></div>
          <p className="mt-2 text-sm leading-snug text-ink-900">“Beaches for me, but ₹8,000 is my limit.”</p>
        </div>
        <div className="absolute bottom-[16%] right-8 w-60 animate-float-slow rounded-3xl border border-white/80 bg-white/90 p-4 shadow-float backdrop-blur-xl">
          <p className="text-xs font-bold uppercase tracking-[.14em] text-lagoon-700">MileMates AI</p>
          <p className="mt-1.5 text-sm leading-snug text-ink-900">Compromise found: ₹6,500 pp with one splurge day.</p>
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
        className="absolute right-1 top-[26px] flex min-h-[44px] min-w-[44px] items-center justify-center rounded-xl p-2 text-ink-500 hover:bg-lagoon-50 hover:text-lagoon-700">
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
      footer={<>New to MileMates? <Link className="font-semibold text-lagoon-700 underline" to="/register">Create an account</Link></>}>
      <form onSubmit={submit} noValidate className="space-y-3.5">
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
    <Frame wide title="Create your account" subtitle="It takes a minute. Then start a trip and invite your group."
      footer={<>Already have an account? <Link className="font-semibold text-lagoon-700 underline" to="/login">Log in</Link></>}>
      <form onSubmit={submit} noValidate className="space-y-3.5">
        {formError && <Alert>{formError}</Alert>}
        <div className="grid gap-3.5 sm:grid-cols-2">
          <Input label="Full name" autoComplete="name" value={v.name} onChange={(e) => set("name")(e.target.value)} error={errors.name} />
          <Input label="Email" type="email" autoComplete="email" value={v.email} onChange={(e) => set("email")(e.target.value)} error={errors.email} />
          <PasswordInput label="Password" autoComplete="new-password" value={v.password} onChange={set("password")} error={errors.password} />
          <PasswordInput label="Confirm password" autoComplete="new-password" value={v.confirm} onChange={set("confirm")} error={errors.confirm} />
        </div>
        <ul className="flex flex-wrap gap-x-4 gap-y-1 text-xs" aria-label="Password requirements">
          {passwordChecks(v.password).map((c) => (
            <li key={c.id} className={`flex items-center gap-1 ${c.ok ? "text-lagoon-700" : "text-ink-500"}`}>
              <Check className={`h-3.5 w-3.5 ${c.ok ? "" : "opacity-30"}`} aria-hidden />{c.label}<span className="sr-only">{c.ok ? " (met)" : " (not met yet)"}</span>
            </li>))}
        </ul>
        <div>
          <label className="flex items-start gap-2 text-[13px] leading-snug text-ink-700">
            <input type="checkbox" checked={terms} onChange={(e) => setTerms(e.target.checked)} className="mt-0.5 h-4 w-4 shrink-0 rounded border-sand-300 accent-lagoon-600" />
            <span>I understand this is a student project and that AI-generated plans are suggestions that need checking before I book anything.</span>
          </label>
          {errors.terms && <p role="alert" className="mt-1 text-sm text-coral-700">{errors.terms}</p>}
        </div>
        <Button type="submit" loading={busy} className="w-full">{busy ? "Creating account…" : "Create account"}</Button>
      </form>
    </Frame>
  );
}
