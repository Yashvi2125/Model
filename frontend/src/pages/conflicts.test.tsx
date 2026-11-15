import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Outlet, Route, Routes } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import { AuthProvider } from "../context/AuthContext";
import { ToastProvider } from "../context/Toast";
import Conflicts from "./trip/Conflicts";

const trip = { id: 7, name: "T", my_role: "owner", currency: "INR", members: [] } as any;
const json = (b: unknown, status = 200) => new Response(JSON.stringify(b), { status, headers: { "Content-Type": "application/json" } });
const me = { id: 1, name: "Asha Patel", email: "a@b.co", created_at: "2026-01-01T00:00:00Z" };
const conflict = (votes: Record<string, string>, status = "open") => ({ id: 1, kind: "budget", title: "Your group has different budget limits", description: "d",
  positions: [{ name: "Asha", detail: "up to ₹20,000" }], suggestion: "Aim for ₹12,000 each", status, votes, generated_by: "ai", created_at: "", decided_at: null });

function mount(handler: (url: string, init?: RequestInit) => Response) {
  vi.stubGlobal("fetch", vi.fn((u: string, i?: RequestInit) => Promise.resolve(handler(u, i))));
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(<QueryClientProvider client={qc}><MemoryRouter initialEntries={["/c"]}><ToastProvider><AuthProvider>
    <Routes><Route element={<Outlet context={{ trip, socket: {} }} />}><Route path="/c" element={<Conflicts />} /></Route></Routes>
  </AuthProvider></ToastProvider></MemoryRouter></QueryClientProvider>);
}
afterEach(() => vi.unstubAllGlobals());

describe("Conflicts page", () => {
  it("shows a vote after analysing (no stale result)", async () => {
    let votes: Record<string, string> = {};
    mount((url, init) => {
      if (url.endsWith("/api/auth/me")) return json(me);
      if (url.endsWith("/conflicts/analyze")) return json({ conflicts: [conflict({})], member_count: 2, members_sharing: 2, ai_error: null });
      if (url.endsWith("/conflicts/1/vote")) { votes = { "1": JSON.parse(String(init!.body)).vote }; return json({ conflicts: [conflict(votes)], member_count: 2, members_sharing: 2, ai_error: null }); }
      return json({ conflicts: [], member_count: 2, members_sharing: 2, ai_error: null });
    });
    await userEvent.click(await screen.findByRole("button", { name: /check for disagreements/i }));
    const agree = await screen.findByRole("button", { name: /i agree/i });
    expect(agree).toHaveAttribute("aria-pressed", "false");
    expect(screen.getByText(/0 agree, 0 disagree/)).toBeInTheDocument();
    await userEvent.click(agree);
    await waitFor(() => expect(screen.getByRole("button", { name: /i agree/i })).toHaveAttribute("aria-pressed", "true"));
    expect(screen.getByText(/1 agree, 0 disagree/)).toBeInTheDocument();
  });

  it("explains why nothing is shown when you are the only member", async () => {
    mount((url) => (url.endsWith("/api/auth/me") ? json(me) : json({ conflicts: [], member_count: 1, members_sharing: 1, ai_error: null })));
    expect(await screen.findByText(/only member so far/i)).toBeInTheDocument();
  });

  it("asks members to share preferences when too few have", async () => {
    mount((url) => (url.endsWith("/api/auth/me") ? json(me) : json({ conflicts: [], member_count: 3, members_sharing: 1, ai_error: null })));
    expect(await screen.findByText(/only 1 of 3 members/i)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /open preferences/i })).toBeInTheDocument();
  });
});
