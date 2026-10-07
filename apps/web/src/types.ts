import type { Result } from "../../mcp-app/src/schema";
import type { Schema, Value } from "./schema-form";

export type Session = {
  authenticated: boolean;
  member?: { member_id: string; display_name: string; role: string };
};
export type Plan = NonNullable<Result["data"]["plan"]>;
export type Review = {
  recorded?: boolean;
  id: string;
  candidate_hash: string;
  sentence: string;
  candidate: string;
  review: { lines: string[]; yaml_diff: string; cedar: string; analysis: string };
};
export type Constitution = {
  recorded_demo: boolean;
  yaml: string;
  document: Value;
  schema: Schema;
  version: number;
  status: string;
  history: { version: number; status: string; yaml: string }[];
  drafting: string;
  proposals: {
    id: string;
    text: string;
    author: string | null;
    surface: string;
    status: string;
    failure: string | null;
    draft_id: string | null;
  }[];
  drafts: (Review & { status: string })[];
};
export type Action = {
  action_id: string;
  class: string;
  reason: string;
  content_hash: string;
  params: Record<string, Value>;
  plan_id: string | null;
  target: { adapter: string; entity: string };
};
export type Pending = {
  risk_band: string;
  id: string;
  status: string;
  expires_at: string;
  quorum: string;
  action: Action;
};
export type TwinRun = {
  id: string;
  scenario: string;
  at: string;
  refreshing: boolean;
  controls: { paused: boolean; speed: number };
  snapshot: {
    status: string;
    error?: string;
    claim?: string;
    checkins: { contact: string; requested_at: string; reply_at: string; deadline: string; status: string }[];
    observations?: Value[];
    limitations?: string[];
  } | null;
};
export const requestId = () => crypto.randomUUID();
export const date = (value: string) => new Date(value).toLocaleString();
