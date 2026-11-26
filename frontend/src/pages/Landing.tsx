import { ArrowRight, Calculator, Check, Compass, Handshake, MapPinned, Menu, ScanSearch, Search, Sparkles, Users, Wand2, X } from "lucide-react";
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { Logo } from "../components/Logo";
import { useAuth } from "../context/AuthContext";

/* ───────────────────────── Hero visual ───────────────────────── */
function HeroScene() {
  return (
    <div className="relative mx-auto w-full max-w-xl">
      <div className="absolute -inset-6 rounded-[3rem] bg-gradient-to-br from-lagoon-200/60 via-sun-100 to-coral-100/60 blur-2xl" aria-hidden />
      <div className="relative overflow-hidden rounded-[2.25rem] shadow-float ring-1 ring-white/70">
        <svg viewBox="0 0 560 560" className="block w-full" role="img"
          aria-label="Illustration of a winding trail across hills and a lake, linking three travellers’ pins">
          <defs>
            <linearGradient id="sky" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stopColor="#FCE9C4" /><stop offset="1" stopColor="#F6F1E7" /></linearGradient>
            <linearGradient id="hill1" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stopColor="#B7E0DA" /><stop offset="1" stopColor="#9FD3CC" /></linearGradient>
          </defs>
          <rect width="560" height="560" fill="url(#sky)" />
          <circle cx="410" cy="140" r="90" fill="#E9A23B" opacity=".18" />
          <circle cx="410" cy="140" r="58" fill="#E9A23B" />
          <g fill="#fff" opacity=".85"><ellipse cx="120" cy="110" rx="46" ry="12" /><ellipse cx="150" cy="98" rx="30" ry="10" /><ellipse cx="300" cy="70" rx="38" ry="10" /></g>
          <path d="M0 340 L110 225 L190 305 L300 185 L410 300 L480 245 L560 310 V560 H0Z" fill="url(#hill1)" />
          <path d="M0 400 L90 320 L180 385 L280 305 L390 390 L470 340 L560 385 V560 H0Z" fill="#14958F" />
          <path d="M0 470 Q140 430 280 470 T560 460 V560 H0Z" fill="#0F7C77" />
          <ellipse cx="170" cy="515" rx="130" ry="16" fill="#0B4D4B" opacity=".5" />
          <path className="animate-dash" d="M70 505 C140 410 220 470 290 385 S430 320 490 225" fill="none" stroke="#FBF8F2" strokeWidth="4.5" strokeLinecap="round" strokeDasharray="2 13" />
          {([[70, 505, "A", "#E9A23B"], [290, 385, "R", "#D9644A"], [490, 225, "S", "#14233D"]] as const).map(([x, y, t, c]) => (
            <g key={t}>
              <ellipse cx={x} cy={y + 6} rx="14" ry="5" fill="#0B4D4B" opacity=".35" />
              <path d={`M${x} ${y + 4} l-17 -32 a21 21 0 1 1 34 0z`} fill={c} />
              <text x={x} y={y - 27} textAnchor="middle" fontSize="17" fontWeight="700" fill="#fff">{t}</text>
            </g>))}
        </svg>
      </div>

      {/* floating chat card */}
      <div className="absolute -left-4 bottom-10 w-64 animate-float rounded-3xl border border-white/80 bg-white/90 p-4 shadow-float backdrop-blur-xl sm:-left-12">
        <div className="flex items-center gap-2.5">
          <span className="flex h-8 w-8 items-center justify-center rounded-full bg-gradient-to-br from-sun-100 to-[#F8D99B] text-xs font-bold text-sun-700">A</span>
          <p className="text-xs font-semibold text-ink-500">Asha · Group chat</p>
        </div>
        <p className="mt-2.5 text-sm leading-snug">“I’d love heritage sites, and ₹8,000 each is my limit.”</p>
        <div className="mt-3 flex flex-wrap gap-1.5">
          <span className="rounded-full bg-lagoon-50 px-2.5 py-0.5 text-xs font-semibold text-lagoon-800 ring-1 ring-inset ring-lagoon-200">Culture</span>
          <span className="rounded-full bg-sun-100 px-2.5 py-0.5 text-xs font-semibold text-sun-700 ring-1 ring-inset ring-sun-500/30">≤ ₹8,000 pp</span>
        </div>
      </div>

      {/* floating AI card */}
      <div className="absolute -right-3 top-8 w-56 animate-float-slow rounded-3xl bg-lagoon-800 p-4 text-white shadow-float sm:-right-8">
        <div className="flex items-center gap-2 text-xs font-semibold text-sun-500"><Sparkles className="h-3.5 w-3.5" aria-hidden />MileMates AI</div>
        <p className="mt-2 text-sm leading-snug text-lagoon-50">Found a compromise: ₹6,500 pp with one splurge day.</p>
        <div className="mt-3 flex items-center gap-2 text-xs text-lagoon-100">
          <span className="flex -space-x-1.5">{["bg-sun-500", "bg-coral-500", "bg-lagoon-200"].map((c) => <span key={c} className={`h-5 w-5 rounded-full ring-2 ring-lagoon-800 ${c}`} />)}</span>3 agreed
        </div>
      </div>
    </div>
  );
}

/* ───────────────────────── Content ───────────────────────── */
const features = [
  { icon: Users, title: "Plan together, not in a pile of messages", text: "Every trip has its own group chat and a code or link to invite friends.", span: "md:col-span-2", accent: "from-lagoon-50 to-white" , chips: ["Group chat", "Invite code", "Live presence"] },
  { icon: ScanSearch, title: "Preferences pulled out of the conversation", text: "Mention @ai and MileMates AI notes budgets, interests and dietary needs as suggestions you review — never silently applied.", span: "", accent: "from-sun-100/70 to-white" , chips: ["@ai", "You approve", "Budgets & diets"] },
  { icon: Handshake, title: "Disagreements made visible", text: "See where budgets, dates or activity tastes differ, get a compromise proposal, and agree on it as a group.", span: "", accent: "from-coral-100/60 to-white" , chips: ["Compromise", "Group vote"] },
  { icon: Compass, title: "Day-by-day itineraries", text: "A Planner and a Researcher agent draft morning, afternoon and evening plans, using live web research when it’s configured.", span: "md:col-span-2", accent: "from-lagoon-100/70 to-white" , chips: ["Morning", "Afternoon", "Evening"] },
  { icon: Calculator, title: "Budget maths you can trust", text: "Totals and per-person splits are calculated in code from the costs in your plan, and clearly marked as estimates.", span: "", accent: "from-lagoon-50 to-white" , chips: ["Per-person split", "Estimates"] },
  { icon: MapPinned, title: "Map and weather for your destination", text: "See where you’re headed and the outlook, without leaving the trip.", span: "md:col-span-2", accent: "from-sun-100/70 to-lagoon-50" , chips: ["Map", "Weather", "Places"] },
];

const steps = [
  { title: "Create a trip and invite friends", text: "Set dates, a rough budget and interests, then share the trip code." },
  { title: "Share preferences in the group chat", text: "Chat naturally. Mention @ai when you want MileMates AI to listen or answer." },
  { title: "Let AI analyse and resolve conflicts", text: "Review the differences it finds and vote on suggested compromises." },
  { title: "Review and refine the itinerary and budget", text: "Regenerate with new instructions until everyone’s happy, then use the checklist." },
];

const stats = [["2", "AI agents"], ["8", "planning tools"], ["100%", "group-approved"], ["0", "silent changes"]];
const marquee = ["Group chat", "@ai preferences", "Conflict voting", "Day-by-day plans", "Budget splits", "Live research", "Map & weather", "Pre-trip checklist", "Telegram bridge", "Invite by code"];

export default function Landing() {
  const { user } = useAuth();
  const [scrolled, setScrolled] = useState(false);
  const [menu, setMenu] = useState(false);
  useEffect(() => { const f = () => setScrolled(window.scrollY > 8); f(); window.addEventListener("scroll", f); return () => window.removeEventListener("scroll", f); }, []);
  const links = [["#features", "Features"], ["#how-it-works", "How it works"]] as const;

  return (
    <div className="overflow-x-clip">
      <header className="sticky top-0 z-40 px-3 pt-3 sm:px-5">
        <div className={`mx-auto flex max-w-6xl items-center justify-between gap-2 rounded-full px-3 py-2 sm:gap-4 sm:px-4 sm:py-2.5 transition-all duration-300 sm:px-6 ${scrolled ? "glass shadow-card" : "border border-transparent"}`}>
          <Logo />
          <nav aria-label="Primary" className="hidden items-center gap-1 text-[15px] font-semibold text-ink-700 md:flex">
            {links.map(([h, l]) => <a key={h} href={h} className="rounded-full px-4 py-2 transition-colors hover:bg-lagoon-50 hover:text-lagoon-700">{l}</a>)}
          </nav>
          <div className="flex items-center gap-1.5 sm:gap-2">
            {user ? <Link to="/app" className="btn-primary whitespace-nowrap !py-2 text-sm sm:text-[15px]">Open dashboard</Link> : <>
              <Link to="/login" className="btn-ghost !px-3 !py-2 text-sm max-sm:hidden sm:!px-4 sm:text-[15px]">Log in</Link>
              <Link to="/register" className="btn-primary whitespace-nowrap !px-3 !py-2 text-[13px] sm:!px-4 sm:text-[15px]">Create account</Link></>}
            <button className="btn-ghost !p-2 flex min-h-[40px] min-w-[40px] items-center justify-center md:hidden" aria-label={menu ? "Close navigation" : "Open navigation"} aria-expanded={menu} onClick={() => setMenu((m) => !m)}>
              {menu ? <X className="h-5 w-5" /> : <Menu className="h-5 w-5" />}</button>
          </div>
        </div>
        {menu && (
          <div className="glass mx-auto mt-2 max-w-6xl animate-fade-in rounded-3xl p-2 shadow-card md:hidden">
            {links.map(([h, l]) => <a key={h} href={h} onClick={() => setMenu(false)} className="block rounded-2xl px-4 py-3 font-semibold text-ink-700 hover:bg-lagoon-50">{l}</a>)}
            {!user && <Link to="/login" onClick={() => setMenu(false)} className="block rounded-2xl px-4 py-3 font-semibold text-ink-700 hover:bg-lagoon-50 sm:hidden">Log in</Link>}
          </div>)}
      </header>

      <main>
        {/* HERO */}
        <section className="relative">
          <div className="pointer-events-none absolute inset-0 bg-grid mask-fade-b opacity-70" aria-hidden />
          <div className="relative mx-auto grid max-w-6xl items-center gap-16 px-5 pb-24 pt-12 lg:grid-cols-[1.05fr_1fr] lg:pt-20">
            <div>
              <span className="eyebrow animate-fade-up"><Sparkles className="h-3.5 w-3.5" aria-hidden />Multi-agent group trip planner</span>
              <h1 className="mt-6 animate-fade-up text-5xl font-bold leading-[1.02] delay-1 sm:text-6xl lg:text-[4.5rem]">Plan better trips. <span className="text-gradient">Together.</span></h1>
              <p className="mt-6 max-w-xl animate-fade-up text-lg leading-relaxed text-ink-700 delay-2">
                Bring everyone’s travel preferences, budgets and ideas together. Let AI help your group find common ground and create a trip everyone can enjoy.
              </p>
              <div className="mt-9 flex animate-fade-up flex-col flex-wrap gap-3 delay-3 sm:flex-row">
                <Link to={user ? "/app/trips/new" : "/register"} className="btn-primary px-7 py-3.5 text-base">Start Planning</Link>
                <a href="#how-it-works" className="btn-secondary px-7 py-3.5 text-base">Explore How It Works</a>
              </div>
              <ul className="mt-9 flex animate-fade-up flex-wrap gap-x-6 gap-y-2 text-sm font-medium text-ink-500 delay-4">
                {["Free to try", "Invite with a code", "You approve every AI change"].map((t) => (
                  <li key={t} className="flex items-center gap-1.5"><span className="flex h-5 w-5 items-center justify-center rounded-full bg-lagoon-100 text-lagoon-700"><Check className="h-3 w-3" strokeWidth={3} aria-hidden /></span>{t}</li>))}
              </ul>
            </div>
            <HeroScene />
          </div>
        </section>

        {/* MARQUEE */}
        <div className="border-y border-sand-200/80 bg-white/60 py-4 backdrop-blur" aria-hidden>
          <div className="flex w-max animate-drift gap-3">
            {[...marquee, ...marquee].map((m, i) => (
              <span key={i} className="inline-flex items-center gap-2 whitespace-nowrap rounded-full border border-sand-200 bg-white px-4 py-1.5 text-sm font-semibold text-ink-700">
                <span className="h-1.5 w-1.5 rounded-full bg-sun-500" />{m}</span>))}
          </div>
        </div>

        {/* STATS */}
        <section className="mx-auto max-w-6xl px-5 pt-16">
          <dl className="grid grid-cols-2 gap-4 md:grid-cols-4">
            {stats.map(([n, l]) => (
              <div key={l} className="card p-5 text-center">
                <dt className="sr-only">{l}</dt>
                <dd className="font-display text-4xl font-bold text-gradient">{n}</dd>
                <p className="mt-1 text-sm font-medium text-ink-500" aria-hidden>{l}</p>
              </div>))}
          </dl>
        </section>

        {/* FEATURES — bento */}
        <section id="features" className="mx-auto max-w-6xl scroll-mt-24 px-5 py-24">
          <span className="eyebrow">Features</span>
          <h2 className="mt-4 max-w-3xl text-3xl font-bold sm:text-5xl">Everything a group needs to get from “where should we go?” to a plan</h2>
          <div className="mt-12 grid auto-rows-fr gap-4 md:grid-cols-3">
            {features.map(({ icon: Icon, title, text, span, accent, chips }) => (
              <div key={title} className={`card card-hover group relative flex flex-col overflow-hidden bg-gradient-to-br p-6 sm:p-7 ${accent} ${span}`}>
                <span className="flex h-12 w-12 items-center justify-center rounded-2xl bg-white text-lagoon-700 shadow-card ring-1 ring-lagoon-100 transition-transform duration-300 group-hover:-rotate-6 group-hover:scale-110"><Icon className="h-5 w-5" aria-hidden /></span>
                <h3 className="mt-5 text-xl font-semibold">{title}</h3>
                <p className="mt-2 max-w-md leading-relaxed text-ink-500">{text}</p>
                <div className="mt-auto flex flex-wrap gap-2 pt-5">{chips.map((c) => <span key={c} className="rounded-full bg-white/90 px-3 py-1 text-xs font-semibold text-lagoon-800 ring-1 ring-lagoon-100">{c}</span>)}</div>
                <ArrowRight className="absolute bottom-6 right-6 h-5 w-5 -translate-x-2 text-lagoon-600 opacity-0 transition-all duration-300 group-hover:translate-x-0 group-hover:opacity-100" aria-hidden />
              </div>))}
          </div>
        </section>

        {/* AGENTS */}
        <section className="mx-auto max-w-6xl px-5 pb-24">
          <div className="surface-dark rounded-[2.5rem] p-8 shadow-float sm:p-12">
            <div className="pointer-events-none absolute inset-0 bg-dots opacity-50" aria-hidden />
            <div className="relative grid items-center gap-10 lg:grid-cols-2">
              <div>
                <span className="inline-flex items-center gap-2 rounded-full border border-white/20 bg-white/10 px-3.5 py-1.5 text-xs font-bold uppercase tracking-[.14em] text-sun-500"><Wand2 className="h-3.5 w-3.5" aria-hidden />Under the hood</span>
                <h2 className="mt-4 text-3xl font-bold !text-white sm:text-4xl">Two specialised agents. One shared plan.</h2>
                <p className="mt-4 max-w-md leading-relaxed text-lagoon-100">A Planner drafts the day-by-day itinerary while a Researcher fact-checks it against live sources — so the plan is grounded, not guessed.</p>
              </div>
              <div className="grid gap-4 sm:grid-cols-2">
                {[[Compass, "Planner", "Drafts mornings, afternoons and evenings from everyone’s saved preferences."], [Search, "Researcher", "Checks places, prices and hours with live web search when configured."]].map(([I, t, d]) => {
                  const Icon = I as typeof Compass;
                  return (
                    <div key={t as string} className="rounded-3xl border border-white/15 bg-white/10 p-6 backdrop-blur">
                      <span className="flex h-11 w-11 items-center justify-center rounded-2xl bg-sun-500 text-ink-950"><Icon className="h-5 w-5" aria-hidden /></span>
                      <p className="mt-4 font-display text-xl font-bold">{t as string}</p>
                      <p className="mt-1 text-sm leading-relaxed text-lagoon-100">{d as string}</p>
                    </div>);
                })}
              </div>
            </div>
          </div>
        </section>

        {/* HOW IT WORKS */}
        <section id="how-it-works" className="mx-auto max-w-6xl scroll-mt-24 px-5 pb-24">
          <span className="eyebrow">Process</span>
          <h2 className="mt-4 text-3xl font-bold sm:text-5xl">How it works</h2>
          <ol className="relative mt-14 grid gap-6 md:grid-cols-2 lg:grid-cols-4">
            <div className="pointer-events-none absolute left-[12%] right-[12%] top-7 hidden border-t-2 border-dashed border-lagoon-200 lg:block" aria-hidden />
            {steps.map((s, i) => (
              <li key={s.title} className="card card-hover relative p-6 pt-10">
                <span className="absolute -top-5 left-6 flex h-12 w-12 items-center justify-center rounded-2xl bg-gradient-to-br from-lagoon-500 to-lagoon-800 font-display text-xl font-bold text-white shadow-glow ring-4 ring-sand-50">{i + 1}</span>
                <h3 className="text-lg font-semibold">{s.title}</h3>
                <p className="mt-2 leading-relaxed text-ink-500">{s.text}</p>
              </li>))}
          </ol>

          <div className="surface-dark mt-20 flex flex-col items-start gap-6 rounded-[2.5rem] p-8 shadow-float sm:flex-row sm:items-center sm:p-12">
            <div className="pointer-events-none absolute -right-10 -top-16 h-56 w-56 rounded-full bg-sun-500" aria-hidden style={{ boxShadow: "0 0 100px 40px rgba(233,162,59,.35)" }} />
            <Sparkles className="relative hidden h-10 w-10 shrink-0 text-sun-500 sm:block" aria-hidden />
            <div className="relative flex-1"><p className="font-display text-3xl font-bold">Ready to plan with your group?</p><p className="mt-1 text-lagoon-100">Create an account, start a trip, and share the code.</p></div>
            <Link to={user ? "/app/trips/new" : "/register"} className="btn-light relative px-7 py-3.5 text-base">Start Planning</Link>
          </div>
        </section>
      </main>

      <footer className="border-t border-sand-200/80 bg-white/70 backdrop-blur">
        <div className="mx-auto flex max-w-6xl flex-col gap-8 px-5 py-12 md:flex-row md:items-start md:justify-between">
          <div className="max-w-sm"><Logo /><p className="mt-4 text-sm leading-relaxed text-ink-500">
            Multi-Agent Group Trip Planner — a B.Tech CSE minor project (JG University, 2026–27) exploring collaborative travel planning with specialised AI agents.</p></div>
          <div className="text-sm text-ink-500">
            <p className="font-display font-bold text-ink-900">Explore</p>
            <ul className="mt-3 space-y-2"><li><a href="#features" className="hover:text-lagoon-700">Features</a></li><li><a href="#how-it-works" className="hover:text-lagoon-700">How it works</a></li>
              <li><Link to="/login" className="hover:text-lagoon-700">Log in</Link></li><li><Link to="/register" className="hover:text-lagoon-700">Create account</Link></li></ul>
          </div>
          <div className="max-w-xs text-sm text-ink-500">
            <p className="font-display font-bold text-ink-900">Acknowledgements</p>
            <p className="mt-3 leading-relaxed">Powered by Google Gemini and Tavily search when configured. Weather and place lookup by Open-Meteo; maps © OpenStreetMap contributors.</p>
            <p className="mt-2 leading-relaxed">AI suggestions are not bookings — verify prices, hours and availability before you pay.</p>
          </div>
        </div>
      </footer>
    </div>
  );
}
