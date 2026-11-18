export type Role = "admin" | "editor" | "viewer";

export interface User {
  id: number;
  email: string;
  name: string;
  role: Role;
  onboarding_completed: boolean;
  onboarding_state: Record<string, unknown>;
}

export interface Niche { id: number; slug: string; name: string; is_custom: boolean; keywords: string[]; is_kids: boolean }

export interface ChannelSettings {
  target_country: string; primary_audience: string; language: string; voiceover_language: string;
  subtitle_languages: string[]; youtube_category_id: string; content_style: string; visual_style: string;
  voice_style: string; background_music: boolean; burn_subtitles: boolean; made_for_kids: boolean;
  short_duration_seconds: number; long_duration_range: string; shorts_per_day: number; long_per_week: number;
  publish_times: string[]; timezone: string; require_approval: boolean; auto_publish: boolean;
  default_privacy: string; video_quality: string;
}

export interface Channel {
  id: number; title: string; handle: string | null; description: string; thumbnail_url: string | null;
  youtube_channel_id: string | null; is_sandbox: boolean; status: string; authorized: boolean;
  subscriber_count: number; view_count: number; video_count: number; automation_enabled: boolean;
  settings: ChannelSettings; brand: { brand_name: string; tagline: string; primary_color: string; secondary_color: string;
    brand_identity: string; logo_path: string | null; banner_path: string | null };
  niches: Niche[];
}

export interface Trend {
  id: number; channel_id: number; niche: string; source: string; topic: string; title: string; description: string;
  source_channel: string | null; source_url: string | null; published_at: string | null; region: string | null;
  language: string | null; view_count: number; view_velocity: number; competition: number; score: number;
  score_breakdown: Record<string, number | string | Record<string, number>>; suggested_ideas: string[]; status: string;
}

export interface StepState { status: string; output?: Record<string, unknown>; error?: string; note?: string }

export interface Video {
  id: number; channel_id: number; format: "short" | "long"; width: number; height: number; duration_seconds: number | null;
  file_path: string | null; status: string; quality_score: number | null; qa_report: QAReport; cost_usd: number;
  youtube_video_id: string | null; youtube_url: string | null; published_at: string | null; created_at: string;
  metadata?: VideoMeta | null; thumbnail?: string | null; analytics?: Snapshot | null; run_id?: number | null;
  run_status?: string | null; sandbox?: boolean;
}

export interface QAReport {
  score?: number; min_score?: number; passed?: boolean; critical_failures?: string[];
  checks?: Record<string, { passed: boolean; critical: boolean; detail: string; score: number }>;
}

export interface VideoMeta {
  title: string; description: string; tags: string[]; hashtags: string[]; thumbnail_text: string;
  made_for_kids: boolean; contains_synthetic_media: boolean; playlist_id: string | null; category_id: string; language: string;
}

export interface Snapshot {
  views: number; likes: number | null; comments: number | null; watch_time_minutes: number | null;
  avg_view_duration_seconds: number | null; avg_view_percentage: number | null; subscribers_gained: number | null;
  ctr: number | null; revenue_usd: number | null; source: string; window: string;
}

export interface Scene {
  id: number; idx: number; narration: string; on_screen_text: string; visual_prompt: string; estimated_seconds: number;
  voiceover: { path: string; duration_seconds: number; provider: string } | null;
  image: { path: string; provider: string } | null;
}

export interface Run {
  id: number; channel_id: number; status: string; current_step: string | null; last_error: string | null;
  steps: Record<string, StepState>; created_at: string; updated_at: string; title: string; review_script: boolean;
  idea: { id: number; title: string; format: string; target_duration_seconds: number; research_summary: string;
    research_facts: { fact: string; source_url: string; confidence: string }[]; angle: string };
  video: Video | null;
}

export interface RunDetail extends Run {
  sources: { id: number; url: string; title: string; publisher: string; reliability: string }[];
  script: { id: number; title: string; hook: string; body: string; cta: string; originality_score: number | null;
    compliance_report: { passed?: boolean; checks?: { name: string; passed: boolean; critical: boolean; detail: string }[] };
    llm_provider: string; llm_model: string; estimated_duration_seconds: number } | null;
  scenes?: Scene[];
  metadata: VideoMeta | null;
  provenance: { id: number; kind: string; provider: string; path: string; license: { license_type: string; notes: string; verified: boolean } }[];
  approvals: Approval[];
}

export interface Approval {
  id: number; kind: string; target_type: string; target_id: number; status: string; summary: string;
  payload: { suggested_slot?: string; quality_score?: number }; created_at: string; run_id?: number | null;
}

export interface Provider {
  id: number; kind: "llm" | "tts" | "image" | "video"; name: string; display_name: string; base_url: string | null;
  enabled: boolean; is_default: boolean; is_paid: boolean; config: Record<string, unknown>;
  health_status: string; health_message: string; health_checked_at: string | null;
  api_key_set: boolean; api_key_masked: string | null; needs_key: boolean;
  model: { model_name: string; cost_per_1k_input: number; cost_per_1k_output: number; cost_per_unit: number } | null;
}

export interface Catalog {
  niches: { slug: string; name: string; category_id: string; kids: boolean; keywords: string[] }[];
  languages: Record<string, string>; short_durations: number[]; long_ranges: string[];
  budget_modes: Record<string, { label: string; llm: string; tts: string; image: string; video: string }>;
  ypp_targets: { early_access: Record<string, number>; full: Record<string, number> };
  google_oauth_configured: boolean; youtube_api_key_configured: boolean; task_mode: string;
}

export interface AutomationSettings {
  is_running: boolean; paused_reason: string | null; budget_mode: string; monthly_budget_usd: number;
  trend_scan_interval_minutes: number; analytics_interval_hours: number; min_quality_score: number;
  trend_weights: Record<string, number>; unattended_publishing_enabled: boolean; max_similarity: number;
  trademark_blocklist: string[]; data_retention_days: number; notification_prefs: Record<string, boolean>;
  auto_select_topics: boolean; min_trend_score: number; optimization_insights: Record<string, unknown>;
}

export interface Notification { id: number; level: string; title: string; message: string; link: string | null; read: boolean; created_at: string }
