import { Calculator, Compass, Handshake, MapPinned, ScanSearch, Sparkles, Users } from "lucide-react";
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { Logo } from "../components/Logo";
import { useAuth } from "../context/AuthContext";

function HeroScene() {
  return (
    <div className="relative mx-auto w-full max-w-xl">
      <svg viewBox="0 0 560 520" className="w-full rounded-[2rem] shadow-card" role="img"
        aria-label="Illustration of a winding trail across hills and a lake, linking three travellers’ pins">
        <defs>
          <linearGradient id="sky" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stopColor="#FCE9C4" /><stop offset="1" stopColor="#F6F1E7" /></linearGradient>
        </defs>
        <rect width="560" height="520" fill="url(#sky)" />
        <circle cx="400" cy="130" r="54" fill="#E9A23B" />
        <path d="M0 330 L110 215 L190 295 L300 175 L410 290 L480 235 L560 300 V520 H0Z" fill="#9FD3CC" />
        <path d="M0 380 L90 300 L180 365 L280 285 L390 370 L470 320 L560 365 V520 H0Z" fill="#14958F" />
        <path d="M0 440 Q140 400 280 440 T560 430 V520 H0Z" fill="#0F7C77" />
        <ellipse cx="170" cy="478" rx="120" ry="16" fill="#0B4D4B" opacity=".5" />
        <path d="M70 470 C140 380 220 440 290 360 S430 300 490 210" fill="none" stroke="#FBF8F2" strokeWidth="4" strokeLinecap="round" strokeDasharray="1 12" />
        {[[70, 470, "A", "#E9A23B"], [290, 360, "R", "#D9644A"], [490, 210, "S", "#14233D"]].map(([x, y, t, c]) => (
          <g key={String(t)}>
            <path d={`M${x} ${(y as number) + 4} l-16 -30 a20 20 0 1 1 32 0z`} fill={c as string} />
            <text x={x as number} y={(y as number) - 26} textAnchor="middle" fontSize="17" fontWeight="700" fill="#fff">{t}</text>
          </g>))}
      </svg>
      <div className="absolute -bottom-6 -left-3 max-w-[16rem] rounded-2xl border border-sand-200 bg-white p-4 shadow-card sm:-left-8">
        <p className="text-xs font-semibold text-ink-500">Example of a chat message</p>
        <p className="mt-1 text-sm">“I’d love heritage sites, and ₹8,000 each is my limit.”</p>
        <div className="mt-2 flex flex-wrap gap-1.5">
          <span className="rounded-full bg-lagoon-50 px-2.5 py-0.5 text-xs font-semibold text-lagoon-800">Culture</span>
          <span className="rounded-full bg-sun-100 px-2.5 py-0.5 text-xs font-semibold text-sun-700">≤ ₹8,000 pp</span>
        </div>
      </div>
    </div>
  );
}

const features = [
  { icon: Users, title: "Plan together, not in a pile of messages", text: "Every trip has its own group chat and a code or link to invite friends." },
  { icon: ScanSearch, title: "Preferences pulled out of the conversation", text: "Mention @ai and TripMate AI notes budgets, interests and dietary needs as suggestions you review — never silently applied." },
  { icon: Handshake, title: "Disagreements made visible", text: "See where budgets, dates or activity tastes differ, get a compromise proposal, and agree on it as a group." },
  { icon: Calculator, title: "Budget maths you can trust", text: "Totals and per-person splits are calculated in code from the costs in your plan, and clearly marked as estimates." },
  { icon: Compass, title: "Day-by-day itineraries", text: "A Planner and a Researcher agent draft morning, afternoon and evening plans, using live web research when it’s configured." },
  { icon: MapPinned, title: "Map and weather for your destination", text: "See where you’re headed and the outlook, without leaving the trip." },
];

const steps = [
  { title: "Create a trip and invite friends", text: "Set dates, a rough budget and interests, then share the trip code." },
  { title: "Share preferences in the group chat", text: "Chat naturally. Mention @ai when you want TripMate AI to listen or answer." },
  { title: "Let AI analyse and resolve conflicts", text: "Review the differences it finds and vote on suggested compromises." },
  { title: "Review and refine the itinerary and budget", text: "Regenerate with new instructions until everyone’s happy, then use the checklist." },
];

export default function Landing() {
  const { user } = useAuth();
  const [scrolled, setScrolled] = useState(false);
  useEffect(() => { const f = () => setScrolled(window.scrollY > 8); f(); window.addEventListener("scroll", f); return () => window.removeEventListener("scroll", f); }, []);
  return (
    <div>
      <header className={`sticky top-0 z-30 transition-colors ${scrolled ? "border-b border-sand-200 bg-sand-50/90 backdrop-blur" : ""}`}>
        <div className="mx-auto flex max-w-6xl items-center justify-between gap-4 px-5 py-4">
          <Logo />
          <nav aria-label="Primary" className="hidden items-center gap-7 text-[15px] font-medium text-ink-700 md:flex">
            <a href="#features" className="hover:text-lagoon-700">Features</a>
            <a href="#how-it-works" className="hover:text-lagoon-700">How it works</a>
          </nav>
          <div className="flex items-center gap-2">
            {user ? <Link to="/app" className="btn-primary">Open dashboard</Link> : <>
              <Link to="/login" className="btn-ghost">Log in</Link>
              <Link to="/register" className="btn-primary">Create account</Link></>}
          </div>
        </div>
      </header>

      <main>
        <section className="mx-auto grid max-w-6xl items-center gap-14 px-5 pb-20 pt-10 lg:grid-cols-[1.05fr_1fr] lg:pt-16">
          <div>
            <h1 className="text-5xl font-bold leading-[1.02] sm:text-6xl lg:text-7xl">Plan better trips. Together.</h1>
            <p className="mt-6 max-w-xl text-lg leading-relaxed text-ink-700">
              Bring everyone’s travel preferences, budgets and ideas together. Let AI help your group find common ground and create a trip everyone can enjoy.
            </p>
            <div className="mt-8 flex flex-wrap gap-3">
              <Link to={user ? "/app/trips/new" : "/register"} className="btn-primary px-6 py-3 text-base">Start Planning</Link>
              <a href="#how-it-works" className="btn-secondary px-6 py-3 text-base">Explore How It Works</a>
            </div>
          </div>
          <HeroScene />
        </section>

        <section id="features" className="scroll-mt-20 border-y border-sand-200 bg-white">
          <div className="mx-auto max-w-6xl px-5 py-20">
            <h2 className="max-w-2xl text-3xl font-bold sm:text-4xl">Everything a group needs to get from “where should we go?” to a plan</h2>
            <div className="mt-12 grid gap-x-12 gap-y-10 md:grid-cols-2">
              {features.map(({ icon: Icon, title, text }) => (
                <div key={title} className="flex gap-4">
                  <span className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl bg-lagoon-50 text-lagoon-700"><Icon className="h-5 w-5" aria-hidden /></span>
                  <div><h3 className="text-lg font-semibold">{title}</h3><p className="mt-1 text-ink-500">{text}</p></div>
                </div>))}
            </div>
          </div>
        </section>

        <section id="how-it-works" className="mx-auto max-w-6xl scroll-mt-20 px-5 py-20">
          <h2 className="text-3xl font-bold sm:text-4xl">How it works</h2>
          <ol className="mt-12 grid gap-8 md:grid-cols-2 lg:grid-cols-4">
            {steps.map((s, i) => (
              <li key={s.title} className="relative">
                <span className="flex h-10 w-10 items-center justify-center rounded-full bg-lagoon-600 font-display text-lg font-bold text-white">{i + 1}</span>
                <h3 className="mt-4 text-lg font-semibold">{s.title}</h3>
                <p className="mt-1 text-ink-500">{s.text}</p>
              </li>))}
          </ol>
          <div className="mt-14 flex items-center gap-4 rounded-2xl bg-lagoon-800 p-8 text-white">
            <Sparkles className="hidden h-8 w-8 shrink-0 text-sun-500 sm:block" aria-hidden />
            <div className="flex-1"><p className="font-display text-2xl font-bold">Ready to plan with your group?</p><p className="text-lagoon-100">Create an account, start a trip, and share the code.</p></div>
            <Link to={user ? "/app/trips/new" : "/register"} className="btn bg-white text-lagoon-800 hover:bg-sand-100">Start Planning</Link>
          </div>
        </section>
      </main>

      <footer className="border-t border-sand-200 bg-white">
        <div className="mx-auto flex max-w-6xl flex-col gap-6 px-5 py-10 md:flex-row md:items-start md:justify-between">
          <div className="max-w-sm"><Logo /><p className="mt-3 text-sm text-ink-500">
            Multi-Agent Group Trip Planner — a B.Tech CSE minor project (JG University, 2026–27) exploring collaborative travel planning with specialised AI agents.</p></div>
          <div className="text-sm text-ink-500">
            <p className="font-semibold text-ink-900">Explore</p>
            <ul className="mt-2 space-y-1.5"><li><a href="#features" className="hover:underline">Features</a></li><li><a href="#how-it-works" className="hover:underline">How it works</a></li>
              <li><Link to="/login" className="hover:underline">Log in</Link></li><li><Link to="/register" className="hover:underline">Create account</Link></li></ul>
          </div>
          <div className="max-w-xs text-sm text-ink-500">
            <p className="font-semibold text-ink-900">Acknowledgements</p>
            <p className="mt-2">Powered by Google Gemini and Tavily search when configured. Weather and place lookup by Open-Meteo; maps © OpenStreetMap contributors.</p>
            <p className="mt-2">AI suggestions are not bookings — verify prices, hours and availability before you pay.</p>
          </div>
        </div>
      </footer>
    </div>
  );
}
