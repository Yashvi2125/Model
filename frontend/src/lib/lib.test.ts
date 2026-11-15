import { describe, expect, it } from "vitest";
import { dayCount, money, todayISO } from "./format";
import { emailValid, passwordChecks, passwordValid, validateTripStep, type TripDraft } from "./validation";

const draft: TripDraft = { name: "Goa", destination: "Goa", undecided: false, start: "2099-01-10", end: "2099-01-12", travelers: "3", total: "", perPerson: "",
  currency: "INR", flexibility: "flexible", interests: [], otherInterests: "", accommodation: "", dietary: "", accessibility: "", constraints: "", notes: "" };

describe("password rules", () => {
  it("requires length, a letter and a number", () => {
    expect(passwordValid("short1")).toBe(false);
    expect(passwordValid("longpassword")).toBe(false);
    expect(passwordValid("12345678")).toBe(false);
    expect(passwordValid("Sup3rSecret")).toBe(true);
    expect(passwordChecks("abc").filter((c) => c.ok)).toHaveLength(1);
  });
  it("validates emails", () => { expect(emailValid("a@b.co")).toBe(true); expect(emailValid("nope")).toBe(false); });
});

describe("trip step validation", () => {
  const today = todayISO();
  it("accepts a good step 0", () => expect(validateTripStep(0, draft, today)).toEqual({}));
  it("rejects return before departure and past dates", () => {
    expect(validateTripStep(0, { ...draft, end: "2099-01-01" }, today).end).toMatch(/before departure/);
    expect(validateTripStep(0, { ...draft, start: "2000-01-01", end: "2000-01-02" }, today).start).toMatch(/past/);
  });
  it("needs a destination unless undecided", () => {
    expect(validateTripStep(0, { ...draft, destination: "" }, today).destination).toBeTruthy();
    expect(validateTripStep(0, { ...draft, destination: "", undecided: true }, today).destination).toBeUndefined();
  });
  it("checks travellers and budget numbers", () => {
    expect(validateTripStep(0, { ...draft, travelers: "0" }, today).travelers).toBeTruthy();
    expect(validateTripStep(1, { ...draft, total: "-5" }, today).total).toBeTruthy();
    expect(validateTripStep(1, { ...draft, total: "abc" }, today).total).toBeTruthy();
    expect(validateTripStep(1, { ...draft, total: "45000" }, today)).toEqual({});
  });
});

describe("formatting", () => {
  it("formats INR and counts inclusive days", () => {
    expect(money(45000, "INR")).toContain("45,000");
    expect(money(null)).toBe("—");
    expect(dayCount("2027-02-10", "2027-02-13")).toBe(4);
  });
});
