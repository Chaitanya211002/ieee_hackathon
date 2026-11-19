// Mirrors the frozen API contract in CLAUDE.md. Change both together.
export type EntryType = "voice" | "photo" | "video" | "protocol_qa" | "analysis" | "note";
export type NodeName = "M5" | "WIN" | "M1";

export interface Artifact {
  kind: "image" | "plot" | "code" | "transcript";
  path: string;
}

export interface Entry {
  id: string;
  type: EntryType;
  created_at: string;
  summary: string;
  details: Record<string, any>;
  artifacts: Artifact[];
  hash: string;
  prev_hash: string;
  node: NodeName;
}

export interface SoundLabel {
  label: string;
  score: number;
}

export interface VerifyReport {
  ok: boolean;
  entries: number;
  verified: number;
  first_broken: string | null;
  reason?: string;
  head?: string;
}

export interface NodeHealth {
  up: boolean;
  checked: number;
  error: string | null;
  url: string | null;
  models?: string[];
}

export interface JobStatus {
  configured: string;
  serving: string;
  model: string;
}

export interface Status {
  nodes: Record<string, NodeHealth>;
  jobs: Record<string, JobStatus>;
  models: Record<string, string>;
  offline: boolean;
  time: string;
}

export interface Experiment {
  id: string;
  name: string;
  created_at: string;
  entry_count?: number;
}

export interface Protocol {
  source: string;
  chunks: number;
  sections: string[];
}
