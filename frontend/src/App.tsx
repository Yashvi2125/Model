import { Suspense, lazy } from "react";
import { Navigate, Route, Routes, useLocation, useParams } from "react-router-dom";
import { useAuth } from "./context/AuthContext";
import { PageLoader } from "./components/ui";
import AppShell from "./layouts/AppShell";
import TripLayout from "./layouts/TripLayout";
import Landing from "./pages/Landing";
import { Login, Register } from "./pages/AuthPages";
import Overview from "./pages/Overview";
import MyTrips from "./pages/MyTrips";
import CreateTrip from "./pages/CreateTrip";
import JoinTrip from "./pages/JoinTrip";
import { Profile, Settings } from "./pages/Account";
import ChatRedirect from "./pages/ChatRedirect";
import Chat from "./pages/trip/Chat";
import Preferences from "./pages/trip/Preferences";
import Conflicts from "./pages/trip/Conflicts";
import ItineraryPage from "./pages/trip/Itinerary";
import Budget from "./pages/trip/Budget";
const ResearchPage = lazy(() => import("./pages/trip/Research"));
import Checklist from "./pages/trip/Checklist";
import Members from "./pages/trip/Members";

export function RequireAuth({ children }: { children: JSX.Element }) {
  const { user, loading } = useAuth();
  const loc = useLocation();
  if (loading) return <PageLoader label="Checking your session…" />;
  if (!user) return <Navigate to="/login" replace state={{ from: loc.pathname + loc.search }} />;
  return children;
}

function PublicOnly({ children }: { children: JSX.Element }) {
  const { user, loading } = useAuth();
  if (loading) return <PageLoader />;
  return user ? <Navigate to="/app" replace /> : children;
}

/** Invite links look like /join/ABCD2345 — send people to the join screen (after login if needed). */
function JoinLink() {
  const { code } = useParams();
  return <Navigate to={`/app/join?code=${encodeURIComponent(code ?? "")}`} replace />;
}

export default function App() {
  return (
    <Routes>
      <Route path="/" element={<Landing />} />
      <Route path="/login" element={<PublicOnly><Login /></PublicOnly>} />
      <Route path="/register" element={<PublicOnly><Register /></PublicOnly>} />
      <Route path="/join/:code" element={<JoinLink />} />
      <Route path="/app" element={<RequireAuth><AppShell /></RequireAuth>}>
        <Route index element={<Overview />} />
        <Route path="trips" element={<MyTrips />} />
        <Route path="trips/new" element={<CreateTrip />} />
        <Route path="join" element={<JoinTrip />} />
        <Route path="chat" element={<ChatRedirect />} />
        <Route path="profile" element={<Profile />} />
        <Route path="settings" element={<Settings />} />
        <Route path="trips/:tripId" element={<TripLayout />}>
          <Route index element={<Navigate to="chat" replace />} />
          <Route path="chat" element={<Chat />} />
          <Route path="preferences" element={<Preferences />} />
          <Route path="conflicts" element={<Conflicts />} />
          <Route path="itinerary" element={<ItineraryPage />} />
          <Route path="budget" element={<Budget />} />
          <Route path="research" element={<Suspense fallback={<PageLoader />}><ResearchPage /></Suspense>} />
          <Route path="checklist" element={<Checklist />} />
          <Route path="members" element={<Members />} />
        </Route>
      </Route>
      <Route path="*" element={
        <div className="mx-auto max-w-md px-6 py-24 text-center">
          <h1 className="text-3xl font-bold">We couldn’t find that page</h1>
          <p className="mt-2 text-ink-500">The link may be old or mistyped.</p>
          <a className="btn-primary mt-6" href="/">Go to the home page</a>
        </div>} />
    </Routes>
  );
}
