export const API = process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000";
export type CallRecord = {
  id: number; status: string; caller_name: string; customer_name: string;
  call_summary?: string | null; customer_interest_level?: string | null;
  key_topics?: string[]; action_items?: string[]; agent_performance_score?: number | null;
  duration_seconds?: number | null; transcript?: string | null; segments?: {start:number;end:number;text:string;speaker:string;role:string}[];
  error_message?: string | null; created_at?: string | null;
};
