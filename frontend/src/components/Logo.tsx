import { useId } from "react";
import { Link } from "react-router-dom";

export function Mark({ className = "h-9 w-9" }: { className?: string }) {
  const gid = useId().replace(/:/g, "");
  return (
    <svg viewBox="0 0 64 64" className={className} aria-hidden>
      <defs>
        <linearGradient id={gid} x1="0" y1="0" x2="1" y2="1"><stop offset="0" stopColor="#14958F" /><stop offset="1" stopColor="#0B4D4B" /></linearGradient>
      </defs>
      <rect width="64" height="64" rx="18" fill={`url(#${gid})`} />
      <path d="M14 44c8-2 10-14 18-14s9 10 18 4" fill="none" stroke="#FBF8F2" strokeWidth="4" strokeLinecap="round" strokeDasharray="1 7" />
      <circle cx="46" cy="22" r="7" fill="#E9A23B" />
      <circle cx="18" cy="44" r="4" fill="#FBF8F2" />
    </svg>
  );
}

export function Logo({ to = "/", light = false }: { to?: string; light?: boolean }) {
  return (
    <Link to={to} className="group inline-flex items-center gap-2.5" aria-label="MileMates AI home">
      <Mark className="h-9 w-9 shadow-glow transition-transform duration-300 group-hover:-rotate-6 group-hover:scale-105 rounded-[12px]" />
      <span className={`whitespace-nowrap font-display text-[17px] font-bold tracking-tight sm:text-xl ${light ? "text-white" : "text-ink-900"}`}>
        MileMates<span className={light ? "text-sun-500" : "text-lagoon-600"}> AI</span>
      </span>
    </Link>
  );
}
