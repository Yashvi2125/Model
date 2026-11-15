import { Link } from "react-router-dom";

export function Mark({ className = "h-9 w-9" }: { className?: string }) {
  return (
    <svg viewBox="0 0 64 64" className={className} aria-hidden>
      <rect width="64" height="64" rx="16" fill="#0F7C77" />
      <path d="M14 44c8-2 10-14 18-14s9 10 18 4" fill="none" stroke="#FBF8F2" strokeWidth="4" strokeLinecap="round" strokeDasharray="1 7" />
      <circle cx="46" cy="22" r="7" fill="#E9A23B" />
      <circle cx="18" cy="44" r="4" fill="#FBF8F2" />
    </svg>
  );
}

export function Logo({ to = "/", light = false }: { to?: string; light?: boolean }) {
  return (
    <Link to={to} className="inline-flex items-center gap-2.5" aria-label="TripMate AI home">
      <Mark />
      <span className={`font-display text-xl font-bold tracking-tight ${light ? "text-white" : "text-ink-950"}`}>TripMate AI</span>
    </Link>
  );
}
