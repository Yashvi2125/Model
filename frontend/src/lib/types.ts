export interface User { id: number; name: string; email: string; created_at: string }

export interface TripSummary {
  id: number; code: string; name: string; destination: string | null; destination_undecided: boolean;
  start_date: string; end_date: string; travelers_count: number; budget_total: number | null;
  budget_per_person: number | null; currency: string; status: string; member_count: number;
  my_role: "owner" | "member"; last_accessed_at: string | null;
}
export interface Member { user_id: number; name: string; role: string; joined_at: string }
export interface TripDetail extends TripSummary {
  budget_flexibility: string; interests: string[]; accommodation_pref: string | null; dietary: string | null;
  accessibility: string | null; constraints: string | null; notes: string | null; is_joinable: boolean;
  owner_id: number; created_at: string; members: Member[];
}
export interface TripPreview {
  code: string; name: string; destination: string | null; start_date: string; end_date: string;
  member_count: number; owner_name: string; already_member: boolean; trip_id: number | null;
}
export interface TripCreateInput {
  name: string; destination: string | null; destination_undecided: boolean; start_date: string; end_date: string;
  travelers_count: number; budget_total: number | null; budget_per_person: number | null; currency: string;
  budget_flexibility: "strict" | "flexible" | "very_flexible"; interests: string[];
  accommodation_pref: string | null; dietary: string | null; accessibility: string | null;
  constraints: string | null; notes: string | null;
}

export interface ChatMessage {
  id: number; trip_id: number; kind: "user" | "ai" | "system"; sender_id: number | null; sender_name: string;
  content: string; meta: Record<string, unknown>; created_at: string;
}

export interface MemberPreference {
  user_id: number; user_name: string; is_me: boolean; destination: string | null; start_date: string | null;
  end_date: string | null; trip_days: number | null; interests: string[]; budget_min: number | null;
  budget_max: number | null; accommodation: string | null; dietary: string | null; restrictions: string | null;
  notes: string | null; sources: Record<string, "direct" | "ai">; missing: string[]; updated_at: string | null;
}
export interface Suggestion { id: number; user_id: number; message_id: number | null; data: Record<string, unknown>; confidence: number | null; status: string; created_at: string }
export interface PreferencesOverview { members: MemberPreference[]; my_suggestions: Suggestion[]; pending_suggestions_total: number; trip_missing: string[] }
export type PreferenceInput = Partial<Pick<MemberPreference, "destination" | "start_date" | "end_date" | "trip_days" | "interests" | "budget_min" | "budget_max" | "accommodation" | "dietary" | "restrictions" | "notes">>;

export interface Conflict {
  id: number; kind: string; title: string; description: string;
  positions: { user_id?: number; name: string; detail: string }[]; suggestion: string | null;
  status: "open" | "accepted" | "dismissed"; votes: Record<string, "agree" | "disagree">; generated_by: string;
  created_at: string; decided_at: string | null;
}
export interface ConflictsResult { conflicts: Conflict[]; member_count: number; members_sharing: number; ai_error: string | null }

export interface ItineraryDay { day: number; title: string; intro: string; sections: { period: "morning" | "afternoon" | "evening"; content: string }[] }
export interface Itinerary {
  id: number; trip_id: number; version: number; status: "running" | "succeeded" | "failed";
  plan_markdown: string | null; research_markdown: string | null;
  days: { overview?: string; days?: ItineraryDay[]; tail?: string; structured?: boolean; sources?: string[] };
  search_used: boolean; error: string | null; budget_error: string | null; model: string | null;
  instructions: string | null; created_at: string; completed_at: string | null;
}
export interface BudgetData {
  travelers: number; days: number; nights: number; group_budget: number | null; per_person_budget: number | null;
  has_estimate: boolean; categories: { category: string; total: number; per_person: number; share: number }[];
  items: { category: string; label: string; amount: number; basis: string; line_total: number; source_text: string }[];
  total: number | null; per_person: number | null; difference: number | null; within_budget: boolean | null;
  currency: string; flexibility: string; itinerary_version: number | null; budget_error: string | null;
  generating: boolean; members_joined: number;
}
export interface ChecklistItem { id: number; text: string; done: boolean; assignee_id: number | null; position: number; completed_at: string | null }
export interface Research {
  destination: string | null; location: { name: string; country?: string; admin?: string; lat: number; lon: number } | null;
  weather: { days: { date: string; summary: string; max_c: number; min_c: number; rain_chance: number | null }[]; covers_trip: boolean; note: string | null } | null;
  errors: string[]; attribution?: string; unavailable_reason?: string; research_markdown: string | null; sources: string[];
  search_used: boolean | null; itinerary_version: number | null; tavily_configured: boolean;
}
export interface AIStatus { gemini_configured: boolean; tavily_configured: boolean; model: string; ready: boolean; notes: string[] }
