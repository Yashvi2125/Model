import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import App from "../App";
import { AuthProvider } from "../context/AuthContext";
import { ToastProvider } from "../context/Toast";

function mount(path: string, fetchImpl: (url: string, init?: RequestInit) => Response | Promise<Response>) {
  vi.stubGlobal("fetch", vi.fn((url: string, init?: RequestInit) => Promise.resolve(fetchImpl(url, init))));
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}><MemoryRouter initialEntries={[path]}><ToastProvider><AuthProvider><App /></AuthProvider></ToastProvider></MemoryRouter></QueryClientProvider>);
}
const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
const loggedOut = (url: string) => (url.endsWith("/api/auth/me") ? json({ detail: "expired" }, 401) : json({ detail: "x" }, 404));

afterEach(() => vi.unstubAllGlobals());

describe("auth redirects", () => {
  it("sends logged-out visitors from protected routes to login", async () => {
    mount("/app/trips", loggedOut);
    expect(await screen.findByRole("heading", { name: /welcome back/i })).toBeInTheDocument();
  });
  it("lands logged-in users on the dashboard from /login", async () => {
    mount("/login", (url) => url.endsWith("/api/auth/me") ? json({ id: 1, name: "Asha Patel", email: "a@b.co", created_at: "2026-01-01T00:00:00Z" }) : json([]));
    expect(await screen.findByRole("heading", { name: /hello, asha/i })).toBeInTheDocument();
    expect(await screen.findByText(/no adventures planned yet/i)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /create your first trip/i })).toBeInTheDocument();
  });
});

describe("forms", () => {
  it("registration validates before calling the API", async () => {
    const calls: string[] = [];
    mount("/register", (url) => { calls.push(url); return loggedOut(url); });
    await userEvent.click(await screen.findByRole("button", { name: /create account/i }));
    expect(await screen.findByText(/enter your full name/i)).toBeInTheDocument();
    expect(screen.getByText(/valid email/i)).toBeInTheDocument();
    expect(screen.getByText(/accept the terms/i)).toBeInTheDocument();
    expect(calls.some((c) => c.includes("/register"))).toBe(false);
  });
  it("registration shows server errors such as duplicate email", async () => {
    mount("/register", (url) => url.includes("/api/auth/register") ? json({ detail: "An account with this email already exists. Try logging in instead." }, 409) : loggedOut(url));
    await userEvent.type(await screen.findByLabelText("Full name"), "Asha Patel");
    await userEvent.type(screen.getByLabelText("Email"), "asha@example.com");
    await userEvent.type(screen.getByLabelText("Password"), "Sup3rSecret");
    await userEvent.type(screen.getByLabelText("Confirm password"), "Sup3rSecret");
    await userEvent.click(screen.getByRole("checkbox"));
    await userEvent.click(screen.getByRole("button", { name: /create account/i }));
    expect(await screen.findByRole("alert")).toHaveTextContent(/already exists/i);
  });
  it("password visibility toggle works", async () => {
    mount("/login", loggedOut);
    const pw = await screen.findByLabelText("Password");
    expect(pw).toHaveAttribute("type", "password");
    await userEvent.click(screen.getByRole("button", { name: /show password/i }));
    await waitFor(() => expect(pw).toHaveAttribute("type", "text"));
  });
  it("landing page shows the hero copy and auth links", async () => {
    mount("/", loggedOut);
    expect(await screen.findByRole("heading", { name: "Plan better trips. Together." })).toBeInTheDocument();
    for (const l of screen.getAllByRole("link", { name: "Start Planning" })) expect(l).toHaveAttribute("href", "/register");
    expect(screen.getByRole("link", { name: "Explore How It Works" })).toHaveAttribute("href", "#how-it-works");
  });
});
