import { useQuery } from "@tanstack/react-query";
import { LayoutDashboard, LogOut, Map, Menu, MessagesSquare, PlusCircle, Settings, UserRound, Users, X } from "lucide-react";
import { useEffect, useState } from "react";
import { NavLink, Outlet, useLocation, useNavigate } from "react-router-dom";
import { Logo } from "../components/Logo";
import { Avatar } from "../components/ui";
import { useAuth } from "../context/AuthContext";
import { useToast } from "../context/Toast";
import { api } from "../lib/api";
import type { TripSummary } from "../lib/types";

export default function AppShell() {
  const { user, logout } = useAuth();
  const navigate = useNavigate();
  const toast = useToast();
  const loc = useLocation();
  const [open, setOpen] = useState(false);
  useEffect(() => setOpen(false), [loc.pathname]);

  const trips = useQuery({ queryKey: ["trips"], queryFn: () => api<TripSummary[]>("/api/trips") });
  const hasTrips = (trips.data?.length ?? 0) > 0;

  const items = [
    { to: "/app", label: "Overview", icon: LayoutDashboard, end: true },
    { to: "/app/trips", label: "My Trips", icon: Map, end: true },
    { to: "/app/trips/new", label: "Create a Trip", icon: PlusCircle },
    { to: "/app/join", label: "Join a Trip", icon: Users },
    ...(hasTrips ? [{ to: "/app/chat", label: "Group Chat", icon: MessagesSquare }] : []),
    { to: "/app/profile", label: "Profile", icon: UserRound },
    { to: "/app/settings", label: "Settings", icon: Settings },
  ];

  const doLogout = async () => {
    try { await logout(); navigate("/", { replace: true }); }
    catch { toast.error("Couldn’t log out. Please try again."); }
  };

  const nav = (
    <nav aria-label="Main" className="flex h-full flex-col">
      <div className="px-6 pb-4 pt-6"><Logo to="/app" /></div>
      <p className="px-6 pb-2 pt-3 text-[11px] font-bold uppercase tracking-[.16em] text-ink-400">Workspace</p>
      <ul className="flex-1 space-y-1 overflow-y-auto px-3">
        {items.map(({ to, label, icon: Icon, end }) => (
          <li key={to}>
            <NavLink to={to} end={end}
              className={({ isActive }) => `group relative flex items-center gap-3 rounded-2xl px-3.5 py-2.5 text-[15px] font-medium transition-all duration-200 ${isActive ? "bg-lagoon-50 text-lagoon-800 ring-1 ring-lagoon-100" : "text-ink-700 hover:bg-sand-100 hover:text-ink-900"}`}>
              {({ isActive }) => (
                <>
                  {isActive && <span className="absolute -left-3 top-1/2 h-6 w-1 -translate-y-1/2 rounded-r-full bg-lagoon-600" aria-hidden />}
                  <span className={`flex h-8 w-8 items-center justify-center rounded-xl transition-colors ${isActive ? "bg-lagoon-600 text-white shadow-glow" : "bg-sand-100 text-ink-500 group-hover:bg-white group-hover:text-lagoon-700"}`}>
                    <Icon className="h-[17px] w-[17px]" aria-hidden />
                  </span>
                  {label}
                </>
              )}
            </NavLink>
          </li>
        ))}
      </ul>
      <div className="border-t border-sand-200 p-3">
        <div className="mb-1 flex items-center gap-3 rounded-2xl px-2 py-2">
          <Avatar name={user!.name} />
          <div className="min-w-0"><p className="truncate text-sm font-semibold text-ink-900">{user!.name}</p><p className="truncate text-xs text-ink-500">{user!.email}</p></div>
        </div>
        <button onClick={doLogout} className="flex w-full items-center gap-3 rounded-2xl px-3.5 py-2.5 text-[15px] font-medium text-ink-700 transition-colors hover:bg-coral-100 hover:text-coral-700">
          <LogOut className="h-[18px] w-[18px]" aria-hidden />Log out
        </button>
      </div>
    </nav>
  );

  return (
    <div className="min-h-screen lg:flex lg:gap-0">
      <aside className="no-print sticky top-0 hidden h-screen w-72 shrink-0 p-3 lg:block">
        <div className="glass h-full rounded-[2rem] shadow-card ring-1 ring-sand-200/80">{nav}</div>
      </aside>

      <header className="no-print sticky top-0 z-30 flex items-center justify-between border-b border-white/60 bg-white/80 px-4 py-2 backdrop-blur-xl lg:hidden">
        <Logo to="/app" />
        <button className="btn-ghost !p-2 flex min-h-[44px] min-w-[44px] items-center justify-center" aria-label="Open menu" aria-expanded={open} onClick={() => setOpen(true)}><Menu className="h-6 w-6" /></button>
      </header>
      {open && (
        <div className="no-print fixed inset-0 z-40 lg:hidden" role="dialog" aria-modal="true" aria-label="Menu">
          <div className="absolute inset-0 animate-fade-in bg-ink-950/50 backdrop-blur-sm" onClick={() => setOpen(false)} />
          <div className="absolute inset-y-0 left-0 w-80 max-w-[88%] animate-fade-in bg-white shadow-float">
            <button className="absolute right-3 top-5 z-10 flex min-h-[44px] min-w-[44px] items-center justify-center rounded-xl text-ink-700 hover:bg-sand-100" aria-label="Close menu" onClick={() => setOpen(false)}><X className="h-5 w-5" /></button>
            {nav}
          </div>
        </div>
      )}

      <main className="min-w-0 flex-1">
        <div className="mx-auto w-full max-w-6xl animate-fade-up px-3 py-3 sm:px-6 sm:py-6 lg:px-8 lg:py-8"><Outlet /></div>
      </main>
    </div>
  );
}
