import { signal } from '@angular/core';
import {
  ChatbotFile,
  ChatbotItem,
  ChatbotStatus,
  JobFile,
  JobFileErrorCode,
  JobFileState,
  JobStatusResponse,
  TextEntryContentResponse,
} from '../../app/interfaces/chatbot-i';
import { mockChatbots } from '../fixtures/chatbots.fixture';
import { defaultTextEntries } from '../fixtures/files.fixture';

export interface MockChatbotState {
  chatbot: ChatbotItem;
  files: ChatbotFile[];
  jobFiles: JobFile[];
  jobProgress: { current: number; total: number };
  previousStatus?: ChatbotStatus;
}

interface MockSnapshot {
  states: MockChatbotState[];
  textEntries: Record<string, TextEntryContentResponse>;
  scenario: string | null;
}

const SNAPSHOT_KEY_PREFIX = 'mockStore:snapshot';
const CURRENT_SCENARIO_KEY = 'mockStore:currentScenario';

const INGEST_PROGRESSION: JobFileState[] = [
  'pending',
  'downloading',
  'downloaded',
  'ingesting',
  'ingested',
];

class MockStore {
  readonly chatbots = signal<MockChatbotState[]>([]);
  readonly autoAdvance = signal<boolean>(true);
  tickIntervalMs = 1000;

  private textEntries: Record<string, TextEntryContentResponse> = {};
  private tickInterval: ReturnType<typeof setInterval> | null = null;
  private currentScenario: string | null = null;

  constructor() {
    if (!this.restoreSnapshot()) {
      this.reset();
    }
  }

  private snapshotKey(): string {
    return `${SNAPSHOT_KEY_PREFIX}:${this.currentScenario ?? '_default'}`;
  }

  private persist(): void {
    if (typeof localStorage === 'undefined') return;
    try {
      const snap: MockSnapshot = {
        states: this.chatbots(),
        textEntries: this.textEntries,
        scenario: this.currentScenario,
      };
      localStorage.setItem(this.snapshotKey(), JSON.stringify(snap));
    } catch {
      /* quota/serialization errors are non-fatal in mock mode */
    }
  }

  private restoreSnapshot(): boolean {
    if (typeof localStorage === 'undefined') return false;
    try {
      const urlScenario = new URLSearchParams(window.location.search).get('state');
      const fallbackScenario = localStorage.getItem(CURRENT_SCENARIO_KEY);
      this.currentScenario = urlScenario ?? fallbackScenario;
      const raw = localStorage.getItem(this.snapshotKey());
      if (!raw) return false;
      const snap = JSON.parse(raw) as MockSnapshot;
      this.chatbots.set(snap.states);
      this.textEntries = snap.textEntries ?? {};
      return true;
    } catch {
      return false;
    }
  }

  reset(): void {
    this.stopTickLoop();
    this.textEntries = {};
    this.chatbots.set(
      mockChatbots.map((c) => ({
        chatbot: { ...c },
        files: [],
        jobFiles: [],
        jobProgress: { current: 0, total: 0 },
      }))
    );
    this.persist();
  }

  loadScenario(states: MockChatbotState[], scenarioName?: string): void {
    this.stopTickLoop();
    this.currentScenario = scenarioName ?? null;
    if (typeof localStorage !== 'undefined') {
      if (scenarioName) {
        localStorage.setItem(CURRENT_SCENARIO_KEY, scenarioName);
      } else {
        localStorage.removeItem(CURRENT_SCENARIO_KEY);
      }
    }
    this.textEntries = { ...collectTextEntries(states) };
    this.chatbots.set(cloneStates(states));
    this.persist();
    if (this.hasProcessingChatbot() && this.autoAdvance()) {
      this.startTickLoop();
    }
  }

  listChatbots(): ChatbotItem[] {
    return this.chatbots().map((s) => s.chatbot);
  }

  getChatbot(id: string): ChatbotItem | undefined {
    return this.chatbots().find((s) => s.chatbot.id === id)?.chatbot;
  }

  getFiles(id: string): ChatbotFile[] {
    return this.chatbots().find((s) => s.chatbot.id === id)?.files ?? [];
  }

  getJobStatus(id: string): JobStatusResponse {
    const state = this.chatbots().find((s) => s.chatbot.id === id);
    if (!state) {
      return {
        status: 'unknown',
        phase: null,
        progress: null,
        files: [],
        created_at: null,
        started_at: null,
      };
    }
    const total = state.jobProgress.total;
    const current = state.jobProgress.current;
    return {
      status: state.chatbot.status,
      phase: null,
      progress: total > 0
        ? {
            current,
            total,
            percentage: Math.round((current / total) * 100),
            message: null,
          }
        : null,
      files: state.jobFiles,
      created_at: new Date().toISOString(),
      started_at: new Date().toISOString(),
    };
  }

  updateChatbot(id: string, patch: Partial<ChatbotItem>): ChatbotItem | undefined {
    let updated: ChatbotItem | undefined;
    this.chatbots.update((states) =>
      states.map((s) => {
        if (s.chatbot.id !== id) return s;
        updated = { ...s.chatbot, ...patch, updated_at: new Date().toISOString() };
        return { ...s, chatbot: updated };
      })
    );
    this.persist();
    return updated;
  }

  addChatbot(state: MockChatbotState): void {
    this.chatbots.update((states) => [...states, cloneState(state)]);
    for (const entry of Object.values(collectTextEntries([state]))) {
      this.textEntries[entry.id] = entry;
    }
    this.persist();
  }

  deleteChatbot(id: string): void {
    this.chatbots.update((states) => states.filter((s) => s.chatbot.id !== id));
    this.persist();
  }

  setStatus(id: string, status: ChatbotStatus): void {
    this.updateChatbot(id, { status });
  }

  addFile(chatbotId: string, file: ChatbotFile): void {
    this.chatbots.update((states) =>
      states.map((s) => {
        if (s.chatbot.id !== chatbotId) return s;
        const files = [...s.files, file];
        const jobFiles = [
          ...s.jobFiles,
          {
            id: `job-${file.id}`,
            external_file_id: file.id,
            filename: file.filename,
            state: (file.ingestion_state ?? 'pending') as JobFileState,
            error_message: file.ingestion_error,
            error_code: file.ingestion_error_code,
            created_at: new Date().toISOString(),
            updated_at: new Date().toISOString(),
          },
        ];
        return { ...s, files, jobFiles };
      })
    );
    this.persist();
  }

  removeFile(chatbotId: string, fileId: string): void {
    this.chatbots.update((states) =>
      states.map((s) => {
        if (s.chatbot.id !== chatbotId) return s;
        return {
          ...s,
          files: s.files.filter((f) => f.id !== fileId),
          jobFiles: s.jobFiles.filter((j) => j.external_file_id !== fileId),
        };
      })
    );
    delete this.textEntries[fileId];
    this.persist();
  }

  setJobProgress(chatbotId: string, current: number, total: number): void {
    this.chatbots.update((states) =>
      states.map((s) =>
        s.chatbot.id === chatbotId
          ? { ...s, jobProgress: { current, total } }
          : s
      )
    );
    this.persist();
  }

  injectFileError(
    chatbotId: string,
    fileId: string,
    errorCode: JobFileErrorCode = 'empty_content'
  ): void {
    this.chatbots.update((states) =>
      states.map((s) => {
        if (s.chatbot.id !== chatbotId) return s;
        return {
          ...s,
          files: s.files.map((f) =>
            f.id === fileId
              ? {
                  ...f,
                  status: 'error' as const,
                  ingestion_state: 'failed' as const,
                  ingestion_error: 'Could not process file',
                  ingestion_error_code: errorCode,
                }
              : f
          ),
          jobFiles: s.jobFiles.map((j) =>
            j.external_file_id === fileId
              ? {
                  ...j,
                  state: 'failed' as const,
                  error_message: 'Could not process file',
                  error_code: errorCode,
                }
              : j
          ),
        };
      })
    );
    this.persist();
  }

  setTextEntry(
    fileId: string,
    entry: TextEntryContentResponse
  ): void {
    this.textEntries[fileId] = entry;
    this.persist();
  }

  getTextEntry(
    _chatbotId: string,
    fileId: string
  ): TextEntryContentResponse | null {
    return this.textEntries[fileId] ?? null;
  }

  hasProcessingChatbot(): boolean {
    return this.chatbots().some(
      (s) => s.chatbot.status === ChatbotStatus.PROCESSING
    );
  }

  startTickLoop(): void {
    if (this.tickInterval) return;
    if (!this.hasProcessingChatbot()) return;
    this.tickInterval = setInterval(() => {
      if (!this.autoAdvance()) {
        this.stopTickLoop();
        return;
      }
      this.tickOnce();
      if (!this.hasProcessingChatbot()) {
        this.stopTickLoop();
      }
    }, this.tickIntervalMs);
  }

  stopTickLoop(): void {
    if (this.tickInterval) {
      clearInterval(this.tickInterval);
      this.tickInterval = null;
    }
  }

  tickOnce(): void {
    this.chatbots.update((states) =>
      states.map((s) => advanceState(s))
    );
    this.persist();
  }

  beginReindex(chatbotId: string): void {
    this.chatbots.update((states) =>
      states.map((s) => {
        if (s.chatbot.id !== chatbotId) return s;
        const files = s.files.map((f) =>
          f.ingestion_state === 'failed'
            ? { ...f, ingestion_state: 'pending' as JobFileState, ingestion_error: null, ingestion_error_code: null, status: 'uploaded' as const }
            : { ...f, ingestion_state: 'pending' as JobFileState }
        );
        const jobFiles = files.map((f) => ({
          id: `job-${f.id}`,
          external_file_id: f.id,
          filename: f.filename,
          state: 'pending' as JobFileState,
          error_message: null,
          error_code: null,
          created_at: new Date().toISOString(),
          updated_at: new Date().toISOString(),
        }));
        return {
          ...s,
          previousStatus: s.chatbot.status,
          chatbot: { ...s.chatbot, status: ChatbotStatus.PROCESSING },
          files,
          jobFiles,
          jobProgress: { current: 0, total: files.length },
        };
      })
    );
    this.persist();
    if (this.autoAdvance()) this.startTickLoop();
  }

  cancelReindex(chatbotId: string): ChatbotStatus {
    let restored = ChatbotStatus.READY;
    this.chatbots.update((states) =>
      states.map((s) => {
        if (s.chatbot.id !== chatbotId) return s;
        restored = s.previousStatus ?? ChatbotStatus.READY;
        return {
          ...s,
          chatbot: { ...s.chatbot, status: restored },
          previousStatus: undefined,
        };
      })
    );
    this.persist();
    if (!this.hasProcessingChatbot()) this.stopTickLoop();
    return restored;
  }
}

function cloneState(s: MockChatbotState): MockChatbotState {
  return {
    chatbot: { ...s.chatbot },
    files: s.files.map((f) => ({ ...f })),
    jobFiles: s.jobFiles.map((j) => ({ ...j })),
    jobProgress: { ...s.jobProgress },
    previousStatus: s.previousStatus,
  };
}

function cloneStates(states: MockChatbotState[]): MockChatbotState[] {
  return states.map(cloneState);
}

function collectTextEntries(
  states: MockChatbotState[]
): Record<string, TextEntryContentResponse> {
  const out: Record<string, TextEntryContentResponse> = {};
  for (const state of states) {
    for (const file of state.files) {
      if (!file.is_free_text) continue;
      const seed = defaultTextEntries[file.id];
      out[file.id] = {
        id: file.id,
        title: seed?.title ?? file.filename,
        content: seed?.content ?? '',
      };
    }
  }
  return out;
}

function advanceState(s: MockChatbotState): MockChatbotState {
  if (s.chatbot.status !== ChatbotStatus.PROCESSING) return s;

  let advanced = false;
  const nextFiles = s.files.map((f) => {
    if (advanced) return f;
    if (f.ingestion_state == null) return f;
    if (f.ingestion_state === 'ingested' || f.ingestion_state === 'failed') return f;
    const idx = INGEST_PROGRESSION.indexOf(f.ingestion_state);
    if (idx < 0 || idx === INGEST_PROGRESSION.length - 1) return f;
    advanced = true;
    const next = INGEST_PROGRESSION[idx + 1]!;
    return { ...f, ingestion_state: next, status: (next === 'ingested' ? 'uploaded' : 'processing') as ChatbotFile['status'] };
  });

  const nextJobFiles = s.jobFiles.map((j) => {
    const file = nextFiles.find((f) => f.id === j.external_file_id);
    if (!file) return j;
    return { ...j, state: (file.ingestion_state ?? j.state) as JobFileState };
  });

  const done = nextFiles.filter(
    (f) => f.ingestion_state === 'ingested' || f.ingestion_state === 'failed'
  ).length;
  const total = nextFiles.length;
  const allTerminal = nextFiles.every(
    (f) => f.ingestion_state === 'ingested' || f.ingestion_state === 'failed'
  );
  const anyFailed = nextFiles.some((f) => f.ingestion_state === 'failed');

  const status = allTerminal
    ? anyFailed
      ? ChatbotStatus.ERROR
      : ChatbotStatus.READY
    : ChatbotStatus.PROCESSING;

  return {
    ...s,
    chatbot: { ...s.chatbot, status },
    files: nextFiles,
    jobFiles: nextJobFiles,
    jobProgress: { current: done, total },
  };
}

export const mockStore = new MockStore();

declare global {
  interface Window {
    __mockStore?: MockStore;
  }
}

if (typeof window !== 'undefined') {
  window.__mockStore = mockStore;
}
