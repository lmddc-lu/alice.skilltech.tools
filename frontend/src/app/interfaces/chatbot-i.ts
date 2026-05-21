export type ChatbotPersonaType = 'teacher' | 'studycompanion' | 'custom';

export enum ChatbotStatus {
  READY = 'ready',
  PROCESSING = 'processing',
  ERROR = 'error',
}

export interface ChatbotI {
  id: string;
  name: string;
  description?: string;
  persona?: string;
  personaType: ChatbotPersonaType;
  knowledge_base_id: string;
  user_email: string;
  updated_at: string;
  status: ChatbotStatus;
}

// Mirrors app/models.py:JobFileErrorCode. null means unclassified; UI falls back to ingestion_error.
export type JobFileErrorCode = 'empty_content';

export interface ChatbotFile {
  id: string;
  filename: string;
  size: number;
  mime_type: string;
  upload_date: string;
  status: 'uploaded' | 'processing' | 'error';
  // True for free-text entries; drives the inline edit affordance.
  is_free_text?: boolean;
  // null when the file has never been part of a job.
  ingestion_state: JobFileState | null;
  // Short user-facing error; verbose detail is admin-only.
  ingestion_error: string | null;
  ingestion_error_code: JobFileErrorCode | null;
}

export interface TextEntryDraft {
  title: string;
  content: string;
}

export interface TextEntryContentResponse {
  id: string;
  title: string;
  content: string;
}

export interface MoodleCourseInfo {
  course_id: string;
  course_name: string;
  shortname: string | null;
  description: string;
  category: string;
  course_url: string | null;
  moodle_domain: string;
  selection_key: string;
  total_sections: number;
  total_activities: number;
  datasource_id: string;
  datasource_name: string;
  metadata_synced: boolean;
  last_metadata_sync: string;
  total_files: number;
}

export interface MoodleCoursesData {
  chatbot_id: string;
  chatbot_name: string;
  knowledge_base_id: string;
  linked_moodle_datasources: string[];
  linked_courses: MoodleCourseInfo[];
  available_courses: MoodleCourseInfo[];
  total_linked: number;
  total_available: number;
  total_courses: number;
  message: string | null;
}

export interface MoodleActivityFile {
  id: string;
  filename: string;
  filesize: number;
  mimetype: string;
  selection_key: string;
  download_url: string;
}

export interface MoodleActivity {
  id: string;
  name: string;
  type: string;
  description: string;
  files: MoodleActivityFile[];
  has_indexed_content: boolean;
}

export interface MoodleSection {
  id: string;
  name: string;
  section_number: number;
  summary: string;
  activities: MoodleActivity[];
  has_indexed_content: boolean;
}

export interface MoodleCourseStructure {
  course_id: string;
  course_name: string;
  sections: MoodleSection[];
}

export type DatasourceType = 'FILE' | 'MOODLE';

export type ReindexFrequency = 'weekly' | 'monthly';

export interface ReindexSchedule {
  chatbot_id: string;
  enabled: boolean;
  frequency: ReindexFrequency | null;
  // 0=Mon..6=Sun (APScheduler convention).
  day_of_week: number | null;
  // 1..28 (capped to avoid short-month edge cases).
  day_of_month: number | null;
  hour: number | null;
  minute: number;
}

export interface ChatbotItem {
  id: string;
  name: string;
  description: string | null;
  persona: string | null;
  personaType: ChatbotPersonaType;
  updated_at: string;
  enabled: boolean;
  access_level : 'public' | 'private' | 'password';
  password : string | null;
  api_enabled: boolean;
  token: string | null;
  status: ChatbotStatus;
  chatbot_url: string;
  chatbot_token: string;
  datasource_types: DatasourceType[];
  prompt_suggestions: string[] | null;
  cite_sources: boolean;
  force_ocr: boolean;
  persist_session: boolean;
  avatar_storage_path: string | null;
  avatar_url: string | null;
  reindex_schedule_enabled: boolean;
  reindex_schedule_frequency: ReindexFrequency | null;
  reindex_schedule_day_of_week: number | null;
  reindex_schedule_day_of_month: number | null;
  reindex_schedule_hour: number | null;
  reindex_schedule_minute: number;
}
export enum ChatbotAccessLevel {
  PUBLIC = 'public',
  PASSWORD = 'password',
  PRIVATE = 'private',
}

export interface FileParsedContent {
  file_name: string;
  total_chunks: number;
  content: string;
}

export interface JobProgress {
  current: number;
  total: number;
  percentage: number;
  message: string | null;
}

export type JobFileState =
  | 'pending'
  | 'downloading'
  | 'downloaded'
  | 'ingesting'
  | 'ingested'
  | 'skipped'
  | 'failed';

export interface JobFile {
  id: string;
  external_file_id: string;
  filename: string;
  state: JobFileState;
  error_message: string | null;
  error_code: JobFileErrorCode | null;
  created_at: string;
  updated_at: string;
}

export type JobPhase = 'waiting_metadata';

export interface JobStatusResponse {
  status: string;
  phase: JobPhase | null;
  progress: JobProgress | null;
  files: JobFile[];
  created_at: string | null;
  started_at: string | null;
}

export interface ChatbotInfoResponse {
  id: string;
  access_level: ChatbotAccessLevel;
  enabled: boolean;
  status: ChatbotStatus;
}

export interface ChatbotPublicInfo {
  id: string;
  name: string;
  description: string | null;
  status: ChatbotStatus;
  enabled: boolean;
  access_level: ChatbotAccessLevel;
  personaType: ChatbotPersonaType;
  prompt_suggestions: string[] | null;
  avatar_url: string | null;
  persist_session: boolean;
}