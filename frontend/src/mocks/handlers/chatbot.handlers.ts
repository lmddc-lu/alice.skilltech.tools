import { http, HttpResponse } from 'msw';
import { environment } from '../../environments/environment';
import { mockStore, MockChatbotState } from '../store/mock-store';
import { toChatbotI } from '../fixtures/chatbots.fixture';
import {
  ChatbotFile,
  ChatbotItem,
  ChatbotStatus,
  JobFileState,
} from '../../app/interfaces/chatbot-i';

const api = environment.apiBaseUrl;
const base = `${api}/chatbots`;

interface StagedTextEntryPayload {
  title: string;
  content: string;
  file_id_to_replace?: string;
}

function uid(prefix: string): string {
  return `${prefix}-${Math.random().toString(36).slice(2, 8)}-${Date.now().toString(36)}`;
}

function fileFromUpload(file: File, pending = true): ChatbotFile {
  return {
    id: uid('file'),
    filename: file.name,
    size: file.size,
    mime_type: file.type || 'application/octet-stream',
    upload_date: new Date().toISOString(),
    status: pending ? 'processing' : 'uploaded',
    ingestion_state: pending ? ('pending' as JobFileState) : ('ingested' as JobFileState),
    ingestion_error: null,
    ingestion_error_code: null,
  };
}

function fileFromTextEntry(title: string): ChatbotFile {
  return {
    id: uid('file-text'),
    filename: title,
    size: 1024,
    mime_type: 'text/plain',
    upload_date: new Date().toISOString(),
    status: 'uploaded',
    is_free_text: true,
    ingestion_state: 'pending' as JobFileState,
    ingestion_error: null,
    ingestion_error_code: null,
  };
}

function newChatbot(
  name: string,
  description: string | null,
  personaType: 'teacher' | 'studycompanion' | 'custom',
  persona: string | null,
  citeSources: boolean,
  forceOcr: boolean,
  promptSuggestions: string[] | null,
  datasourceTypes: ('FILE' | 'MOODLE')[]
): ChatbotItem {
  const id = uid('cb');
  return {
    id,
    name,
    description,
    persona,
    personaType,
    updated_at: new Date().toISOString(),
    enabled: true,
    access_level: 'public',
    password: null,
    api_enabled: false,
    token: null,
    status: ChatbotStatus.PROCESSING,
    chatbot_url: `https://example.com/chat/${id}`,
    chatbot_token: `token-${id}`,
    datasource_types: datasourceTypes,
    prompt_suggestions: promptSuggestions,
    cite_sources: citeSources,
    force_ocr: forceOcr,
    persist_session: false,
    avatar_storage_path: null,
    avatar_url: null,
    reindex_schedule_enabled: false,
    reindex_schedule_frequency: null,
    reindex_schedule_day_of_week: null,
    reindex_schedule_day_of_month: null,
    reindex_schedule_hour: null,
    reindex_schedule_minute: 0,
  };
}

async function buildStateFromFormData(
  request: Request,
  datasourceTypes: ('FILE' | 'MOODLE')[]
): Promise<MockChatbotState> {
  const formData = await request.formData();
  const name = (formData.get('name') as string) ?? 'Nouveau chatbot';
  const description = (formData.get('description') as string) || null;
  const personaType =
    ((formData.get('persona_type') as string) as 'teacher' | 'studycompanion' | 'custom') ||
    'teacher';
  const persona = (formData.get('persona') as string) || null;
  const citeSources = (formData.get('cite_sources') as string) === 'true';
  const forceOcr = (formData.get('force_ocr') as string) === 'true';
  const rawSuggestions = formData.get('prompt_suggestions') as string | null;
  const promptSuggestions = rawSuggestions
    ? (JSON.parse(rawSuggestions) as string[])
    : null;
  const rawEntries = formData.get('text_entries') as string | null;
  const textEntries = rawEntries
    ? (JSON.parse(rawEntries) as { title: string; content: string }[])
    : [];

  const uploaded = formData.getAll('files').filter((x): x is File => x instanceof File);
  const files: ChatbotFile[] = [
    ...uploaded.map((f) => fileFromUpload(f)),
    ...textEntries.map((t) => fileFromTextEntry(t.title)),
  ];

  const chatbot = newChatbot(
    name,
    description,
    personaType,
    persona,
    citeSources,
    forceOcr,
    promptSuggestions,
    datasourceTypes
  );

  const state: MockChatbotState = {
    chatbot,
    files,
    jobFiles: files.map((f) => ({
      id: `job-${f.id}`,
      external_file_id: f.id,
      filename: f.filename,
      state: 'pending' as JobFileState,
      error_message: null,
      error_code: null,
      created_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
    })),
    jobProgress: { current: 0, total: files.length },
  };

  textEntries.forEach((entry, idx) => {
    const freeTextFile = files[uploaded.length + idx];
    if (freeTextFile) {
      mockStore.setTextEntry(freeTextFile.id, {
        id: freeTextFile.id,
        title: entry.title,
        content: entry.content,
      });
    }
  });

  return state;
}

export const chatbotHandlers = [
  http.get(base, () => {
    const items = mockStore.listChatbots().map(toChatbotI);
    return HttpResponse.json(items);
  }),

  http.get(`${base}/:id/details`, ({ params }) => {
    const chatbot = mockStore.getChatbot(params['id'] as string);
    if (!chatbot) return new HttpResponse(null, { status: 404 });
    return HttpResponse.json(chatbot);
  }),

  http.get(`${base}/:id/info`, ({ params }) => {
    const chatbot = mockStore.getChatbot(params['id'] as string);
    if (!chatbot) return new HttpResponse(null, { status: 404 });
    return HttpResponse.json({
      id: chatbot.id,
      name: chatbot.name,
      description: chatbot.description,
      status: chatbot.status,
      enabled: chatbot.enabled,
      access_level: chatbot.access_level,
      personaType: chatbot.personaType,
      prompt_suggestions: chatbot.prompt_suggestions,
    });
  }),

  http.get(`${base}/:id`, ({ params }) => {
    const chatbot = mockStore.getChatbot(params['id'] as string);
    if (!chatbot) return new HttpResponse(null, { status: 404 });
    return HttpResponse.json({
      id: chatbot.id,
      name: chatbot.name,
      description: chatbot.description,
      status: chatbot.status,
      enabled: chatbot.enabled,
      access_level: chatbot.access_level,
      personaType: chatbot.personaType,
      prompt_suggestions: chatbot.prompt_suggestions,
    });
  }),

  http.post(`${base}/:id/access`, async ({ params, request }) => {
    const chatbot = mockStore.getChatbot(params['id'] as string);
    if (!chatbot) return new HttpResponse(null, { status: 404 });
    const body = (await request.json().catch(() => ({}))) as { password?: string };
    if (chatbot.access_level === 'password' && body.password !== chatbot.password) {
      return new HttpResponse(JSON.stringify({ detail: 'Invalid password' }), {
        status: 403,
        headers: { 'Content-Type': 'application/json' },
      });
    }
    return HttpResponse.json({
      id: chatbot.id,
      name: chatbot.name,
      description: chatbot.description,
      status: chatbot.status,
      enabled: chatbot.enabled,
      access_level: chatbot.access_level,
      personaType: chatbot.personaType,
      prompt_suggestions: chatbot.prompt_suggestions,
    });
  }),

  http.post(base, async ({ request }) => {
    const body = (await request.json()) as Partial<ChatbotItem>;
    const chatbot = newChatbot(
      body.name ?? 'Nouveau chatbot',
      body.description ?? null,
      body.personaType ?? 'teacher',
      body.persona ?? null,
      body.cite_sources ?? true,
      body.force_ocr ?? false,
      body.prompt_suggestions ?? null,
      ['FILE']
    );
    chatbot.status = ChatbotStatus.READY;
    mockStore.addChatbot({
      chatbot,
      files: [],
      jobFiles: [],
      jobProgress: { current: 0, total: 0 },
    });
    return HttpResponse.json(chatbot);
  }),

  http.post(`${base}/create-from-files`, async ({ request }) => {
    const state = await buildStateFromFormData(request, ['FILE']);
    mockStore.addChatbot(state);
    mockStore.beginReindex(state.chatbot.id);
    return HttpResponse.json(state.chatbot);
  }),

  http.post(`${base}/create-from-moodle`, async ({ request }) => {
    const state = await buildStateFromFormData(request, ['MOODLE']);
    mockStore.addChatbot(state);
    mockStore.beginReindex(state.chatbot.id);
    return HttpResponse.json(state.chatbot);
  }),

  http.post(`${base}/:id/reindex`, ({ params }) => {
    const id = params['id'] as string;
    if (!mockStore.getChatbot(id)) return new HttpResponse(null, { status: 404 });
    mockStore.beginReindex(id);
    return HttpResponse.json({ job_id: `job-${Date.now()}`, chatbot_id: id });
  }),

  http.post(`${base}/:id/cancel-indexing`, ({ params }) => {
    const id = params['id'] as string;
    const chatbot = mockStore.getChatbot(id);
    if (!chatbot) return new HttpResponse(null, { status: 404 });
    const restored = mockStore.cancelReindex(id);
    return HttpResponse.json({
      message: 'Indexing cancelled',
      chatbot_id: id,
      status: restored,
    });
  }),

  http.patch(`${base}/:id`, async ({ params, request }) => {
    const patch = (await request.json()) as Record<string, unknown>;
    const updated = mockStore.updateChatbot(params['id'] as string, patch as Partial<ChatbotItem>);
    if (!updated) return new HttpResponse(null, { status: 404 });
    return HttpResponse.json(updated);
  }),

  http.delete(`${base}/:id`, ({ params }) => {
    mockStore.deleteChatbot(params['id'] as string);
    return new HttpResponse(null, { status: 204 });
  }),

  http.get(`${base}/:id/files`, ({ params }) => {
    const id = params['id'] as string;
    const files = mockStore.getFiles(id);
    const failed = files.filter((f) => f.ingestion_state === 'failed').length;
    return HttpResponse.json({
      chatbot_id: id,
      files,
      total_files: files.length,
      failed_ingestion_count: failed,
    });
  }),

  http.get(`${base}/:id/job-status`, ({ params }) => {
    return HttpResponse.json(mockStore.getJobStatus(params['id'] as string));
  }),

  http.post(`${base}/:id/add-files`, async ({ params, request }) => {
    const id = params['id'] as string;
    if (!mockStore.getChatbot(id)) return new HttpResponse(null, { status: 404 });
    const formData = await request.formData();
    const uploaded = formData.getAll('files').filter((x): x is File => x instanceof File);
    const newFiles = uploaded.map((f) => fileFromUpload(f));
    newFiles.forEach((f) => mockStore.addFile(id, f));
    mockStore.setStatus(id, ChatbotStatus.PROCESSING);
    mockStore.setJobProgress(id, 0, mockStore.getFiles(id).length);
    if (mockStore.autoAdvance()) mockStore.startTickLoop();
    return HttpResponse.json(newFiles);
  }),

  http.delete(`${base}/:id/files/:fileId`, ({ params }) => {
    mockStore.removeFile(params['id'] as string, params['fileId'] as string);
    return new HttpResponse(null, { status: 204 });
  }),

  http.patch(`${base}/:id/files`, async ({ params, request }) => {
    const id = params['id'] as string;
    if (!mockStore.getChatbot(id)) return new HttpResponse(null, { status: 404 });
    const formData = await request.formData();
    const uploaded = formData.getAll('files').filter((x): x is File => x instanceof File);
    const deleteIdsRaw = formData.get('file_ids_to_delete') as string | null;
    const fileIdsToDelete = deleteIdsRaw ? (JSON.parse(deleteIdsRaw) as string[]) : [];
    const entriesRaw = formData.get('text_entries') as string | null;
    const textEntries = entriesRaw
      ? (JSON.parse(entriesRaw) as StagedTextEntryPayload[])
      : [];

    fileIdsToDelete.forEach((fid) => mockStore.removeFile(id, fid));

    const addedFromFiles = uploaded.map((f) => {
      const file = fileFromUpload(f);
      mockStore.addFile(id, file);
      return {
        id: file.id,
        filename: file.filename,
        size: file.size,
        mime_type: file.mime_type,
      };
    });

    const addedFromEntries = textEntries.map((entry) => {
      if (entry.file_id_to_replace) mockStore.removeFile(id, entry.file_id_to_replace);
      const file = fileFromTextEntry(entry.title);
      mockStore.addFile(id, file);
      mockStore.setTextEntry(file.id, {
        id: file.id,
        title: entry.title,
        content: entry.content,
      });
      return {
        id: file.id,
        filename: file.filename,
        size: file.size,
        mime_type: file.mime_type,
      };
    });

    const filesAdded = [...addedFromFiles, ...addedFromEntries];
    const reindexing = filesAdded.length > 0 || fileIdsToDelete.length > 0;
    if (reindexing) {
      mockStore.beginReindex(id);
    }

    return HttpResponse.json({
      message: 'Files updated',
      chatbot_id: id,
      files_added: filesAdded,
      files_deleted: fileIdsToDelete,
      total_added: filesAdded.length,
      total_deleted: fileIdsToDelete.length,
      reindexing,
    });
  }),

  http.get(`${base}/:id/files/:fileId/parsed-content`, ({ params }) => {
    const files = mockStore.getFiles(params['id'] as string);
    const file = files.find((f) => f.id === params['fileId']);
    if (!file) return new HttpResponse(null, { status: 404 });
    return HttpResponse.json({
      file_name: file.filename,
      total_chunks: 3,
      content: `# ${file.filename}\n\nContenu analysé de démonstration.\n\n## Extrait\n\nCe document couvre les principales notions du chapitre. Lorem ipsum dolor sit amet, consectetur adipiscing elit.\n\n- Point clé 1\n- Point clé 2\n- Point clé 3\n`,
    });
  }),

  http.get(`${base}/:id/files/:fileId/text`, ({ params }) => {
    const entry = mockStore.getTextEntry(
      params['id'] as string,
      params['fileId'] as string
    );
    if (!entry) return new HttpResponse(null, { status: 404 });
    return HttpResponse.json(entry);
  }),

  http.post(`${base}/:id/avatar`, async ({ params, request }) => {
    const id = params['id'] as string;
    if (!mockStore.getChatbot(id)) return new HttpResponse(null, { status: 404 });
    const formData = await request.formData();
    const file = formData.get('file');
    if (!(file instanceof File)) {
      return new HttpResponse(JSON.stringify({ detail: 'Missing file' }), {
        status: 400,
        headers: { 'Content-Type': 'application/json' },
      });
    }
    const avatarUrl = URL.createObjectURL(file);
    const updated = mockStore.updateChatbot(id, {
      avatar_storage_path: `mock/avatars/${id}/${file.name}`,
      avatar_url: avatarUrl,
    });
    return HttpResponse.json(updated);
  }),

  http.delete(`${base}/:id/avatar`, ({ params }) => {
    const id = params['id'] as string;
    if (!mockStore.getChatbot(id)) return new HttpResponse(null, { status: 404 });
    const updated = mockStore.updateChatbot(id, {
      avatar_storage_path: null,
      avatar_url: null,
    });
    return HttpResponse.json(updated);
  }),
];
