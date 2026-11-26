import { CircleAlert, Loader2 } from "lucide-react";
import { forwardRef, useId, type ButtonHTMLAttributes, type InputHTMLAttributes, type ReactNode, type SelectHTMLAttributes, type TextareaHTMLAttributes } from "react";

export function Spinner({ className = "h-4 w-4" }: { className?: string }) {
  return <Loader2 className={`${className} animate-spin`} aria-hidden />;
}

export function Button({ loading, children, variant = "primary", className = "", ...p }:
  ButtonHTMLAttributes<HTMLButtonElement> & { loading?: boolean; variant?: "primary" | "secondary" | "ghost" | "danger" }) {
  return (
    <button {...p} disabled={p.disabled || loading} className={`btn-${variant} ${className}`}>
      {loading && <Spinner />}{children}
    </button>
  );
}

export function PageLoader({ label = "Loading…" }: { label?: string }) {
  return (
    <div className="flex flex-col items-center justify-center gap-4 py-24 text-ink-500" role="status">
      <span className="relative flex h-12 w-12 items-center justify-center">
        <span className="absolute inset-0 animate-pulse-ring rounded-full bg-lagoon-200" aria-hidden />
        <span className="relative flex h-12 w-12 items-center justify-center rounded-full bg-white text-lagoon-600 shadow-card"><Spinner className="h-5 w-5" /></span>
      </span>
      <span className="text-sm font-medium">{label}</span>
    </div>
  );
}

export function Alert({ kind = "error", children, action }: { kind?: "error" | "info" | "warning"; children: ReactNode; action?: ReactNode }) {
  const tone = { error: "border-coral-500/30 bg-coral-100 text-coral-700", info: "border-lagoon-200 bg-lagoon-50 text-lagoon-800", warning: "border-sun-500/40 bg-sun-100 text-sun-700" }[kind];
  return (
    <div role={kind === "error" ? "alert" : "status"} className={`flex flex-wrap items-start gap-3 rounded-2xl border px-3.5 py-3 text-[13px] shadow-sm sm:px-4 sm:py-3.5 sm:text-sm backdrop-blur ${tone}`}>
      <CircleAlert className="mt-0.5 h-4 w-4 shrink-0" aria-hidden />
      <div className="min-w-0 flex-1">{children}</div>
      {action}
    </div>
  );
}

export function QueryError({ error, retry }: { error: unknown; retry?: () => void }) {
  return (
    <Alert action={retry && <button className="font-semibold underline" onClick={retry}>Try again</button>}>
      {error instanceof Error ? error.message : "Something went wrong."}
    </Alert>
  );
}

export function EmptyState({ icon, title, text, action }: { icon?: ReactNode; title: string; text?: string; action?: ReactNode }) {
  return (
    <div className="card relative flex flex-col items-center overflow-hidden px-6 py-14 text-center">
      <div className="pointer-events-none absolute -right-16 -top-16 h-52 w-52 rounded-full bg-lagoon-100/70 blur-3xl" aria-hidden />
      <div className="pointer-events-none absolute -bottom-16 -left-16 h-52 w-52 rounded-full bg-sun-100 blur-3xl" aria-hidden />
      {icon && <div className="relative mb-5 flex h-16 w-16 items-center justify-center rounded-3xl bg-gradient-to-br from-lagoon-50 to-lagoon-100 text-lagoon-700 shadow-card ring-1 ring-lagoon-200/70">{icon}</div>}
      <h3 className="relative text-xl font-semibold">{title}</h3>
      {text && <p className="relative mt-1.5 max-w-md text-ink-500">{text}</p>}
      {action && <div className="relative mt-6">{action}</div>}
    </div>
  );
}

export function Badge({ children, tone = "neutral" }: { children: ReactNode; tone?: "neutral" | "teal" | "amber" | "coral" }) {
  const t = { neutral: "bg-sand-100 text-ink-700 ring-sand-200", teal: "bg-lagoon-50 text-lagoon-800 ring-lagoon-200", amber: "bg-sun-100 text-sun-700 ring-sun-500/30", coral: "bg-coral-100 text-coral-700 ring-coral-500/30" }[tone];
  return <span className={`inline-flex items-center gap-1 rounded-full px-2.5 py-0.5 text-xs font-semibold ring-1 ring-inset ${t}`}>{children}</span>;
}

interface FieldProps { label: string; error?: string; hint?: string; optional?: boolean }

function FieldShell({ label, error, hint, optional, id, children }: FieldProps & { id: string; children: ReactNode }) {
  return (
    <div>
      <label htmlFor={id} className="mb-1.5 flex items-baseline gap-2 text-[13px] font-semibold tracking-wide text-ink-900">
        {label}{optional && <span className="text-xs font-normal text-ink-400">optional</span>}
      </label>
      {children}
      {hint && !error && <p id={`${id}-hint`} className="mt-1 text-xs text-ink-500">{hint}</p>}
      {error && <p id={`${id}-err`} role="alert" className="mt-1 text-sm text-coral-700">{error}</p>}
    </div>
  );
}
const describe = (id: string, e?: string, h?: string) => (e ? `${id}-err` : h ? `${id}-hint` : undefined);

export const Input = forwardRef<HTMLInputElement, InputHTMLAttributes<HTMLInputElement> & FieldProps>(
  ({ label, error, hint, optional, className = "", ...p }, ref) => {
    const id = useId();
    return (
      <FieldShell {...{ label, error, hint, optional, id }}>
        <input ref={ref} id={id} className={`input ${className}`} aria-invalid={!!error} aria-describedby={describe(id, error, hint)} {...p} />
      </FieldShell>
    );
  });

export function Textarea({ label, error, hint, optional, ...p }: TextareaHTMLAttributes<HTMLTextAreaElement> & FieldProps) {
  const id = useId();
  return (
    <FieldShell {...{ label, error, hint, optional, id }}>
      <textarea id={id} className="input min-h-[88px]" aria-invalid={!!error} aria-describedby={describe(id, error, hint)} {...p} />
    </FieldShell>
  );
}

export function Select({ label, error, hint, optional, children, ...p }: SelectHTMLAttributes<HTMLSelectElement> & FieldProps) {
  const id = useId();
  return (
    <FieldShell {...{ label, error, hint, optional, id }}>
      <select id={id} className="input" aria-invalid={!!error} aria-describedby={describe(id, error, hint)} {...p}>{children}</select>
    </FieldShell>
  );
}

export function Avatar({ name, size = "md", tone }: { name: string; size?: "sm" | "md" | "lg"; tone?: number }) {
  const palette = ["from-lagoon-100 to-lagoon-200 text-lagoon-800", "from-sun-100 to-[#F8D99B] text-sun-700", "from-coral-100 to-[#F5C0B2] text-coral-700", "from-sky-100 to-sky-200 text-sky-800", "from-violet-100 to-violet-200 text-violet-800", "from-emerald-100 to-emerald-200 text-emerald-800"];
  const idx = tone ?? [...name].reduce((a, c) => a + c.charCodeAt(0), 0);
  const s = { sm: "h-7 w-7 text-[11px]", md: "h-9 w-9 text-xs", lg: "h-12 w-12 text-base" }[size];
  const init = name.split(/\s+/).filter(Boolean).slice(0, 2).map((p) => p[0]!.toUpperCase()).join("");
  return <span aria-hidden className={`inline-flex shrink-0 items-center justify-center rounded-full bg-gradient-to-br font-bold ring-2 ring-white ${s} ${palette[idx % palette.length]}`}>{init}</span>;
}
