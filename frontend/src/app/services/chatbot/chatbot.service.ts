import { Injectable, inject } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';
import {
  ChatbotI,
  ChatbotItem,
  ChatbotInfoResponse,
  ChatbotPublicInfo,
  ChatbotFile,
  FileParsedContent,
  JobStatusResponse,
  ReindexSchedule,
  TextEntryContentResponse,
  TextEntryDraft,
} from '../../interfaces/chatbot-i';
import { environment } from '../../../environments/environment';

export interface CreateFromFilesData {
  name: string;
  description?: string;
  chatbotType: 'teacher' | 'studycompanion' | 'custom';
  customPersona?: string;
  promptSuggestions?: string[];
  citeSources?: boolean;
  files: File[];
  textEntries?: TextEntryDraft[];
  forceOcr?: boolean;
}

export interface CreateFromMoodleData {
  name: string;
  description?: string;
  chatbotType: 'teacher' | 'studycompanion' | 'custom';
  customPersona?: string;
  promptSuggestions?: string[];
  citeSources?: boolean;
  moodleUrl: string;
  moodleToken: string;
  courseIds: string[];
  files?: File[];
  textEntries?: TextEntryDraft[];
  forceOcr?: boolean;
}

export interface StagedTextEntryPayload {
  title: string;
  content: string;
  file_id_to_replace?: string;
}

export interface ChatbotFilesResponse {
  chatbot_id: string;
  files: ChatbotFile[];
  total_files: number;
  failed_ingestion_count: number;
}

export interface DeleteChatbotResponse {
  message: string;
  chatbot_id: string;
}

export interface UpdateFilesResponse {
  message: string;
  chatbot_id: string;
  files_added: Array<{
    id: string;
    filename: string;
    size: number;
    mime_type: string;
  }>;
  files_deleted: string[];
  total_added: number;
  total_deleted: number;
  reindexing: boolean;
  reindex_error?: string;
}

@Injectable({
  providedIn: 'root',
})
export class ChatbotService {
  private http = inject(HttpClient);
  private baseUrl = `${environment.apiBaseUrl}/chatbots`;

  getChatbots(): Observable<ChatbotI[]> {
    return this.http.get<ChatbotI[]>(this.baseUrl);
  }

  getChatbotById(id: string): Observable<ChatbotItem> {
    return this.http.get<ChatbotItem>(`${this.baseUrl}/${id}/details`);
  }

  getChatbotInfo(id: string): Observable<ChatbotInfoResponse> {
    return this.http.get<ChatbotInfoResponse>(`${this.baseUrl}/${id}/info`);
  }

  accessChatbot(id: string, password?: string): Observable<ChatbotPublicInfo> {
    const body = password ? { password } : {};
    return this.http.post<ChatbotPublicInfo>(
      `${this.baseUrl}/${id}/access`,
      body
    );
  }
  createChatbot(chatbot: Partial<ChatbotI>): Observable<ChatbotItem> {
    return this.http.post<ChatbotItem>(this.baseUrl, chatbot);
  }

  createChatbotFromFiles(data: CreateFromFilesData): Observable<ChatbotItem> {
    const formData = new FormData();

    formData.append('name', data.name);

    if (data.description) {
      formData.append('description', data.description);
    }

    formData.append('persona_type', data.chatbotType);
    if (data.chatbotType === 'custom' && data.customPersona) {
      formData.append('persona', data.customPersona);
    }
    formData.append('cite_sources', String(data.citeSources ?? true));

    if (data.promptSuggestions?.length) {
      formData.append('prompt_suggestions', JSON.stringify(data.promptSuggestions));
    }

    data.files.forEach((file) => {
      formData.append('files', file);
    });

    if (data.textEntries?.length) {
      formData.append('text_entries', JSON.stringify(data.textEntries));
    }

    if (data.forceOcr) {
      formData.append('force_ocr', 'true');
    }

    return this.http.post<ChatbotItem>(
      `${this.baseUrl}/create-from-files`,
      formData
    );
  }

  createChatbotFromMoodle(data: CreateFromMoodleData): Observable<ChatbotItem> {
    const formData = new FormData();

    formData.append('name', data.name);

    if (data.description) {
      formData.append('description', data.description);
    }

    formData.append('persona_type', data.chatbotType);
    if (data.chatbotType === 'custom' && data.customPersona) {
      formData.append('persona', data.customPersona);
    }
    formData.append('cite_sources', String(data.citeSources ?? true));

    if (data.promptSuggestions?.length) {
      formData.append('prompt_suggestions', JSON.stringify(data.promptSuggestions));
    }

    formData.append('moodle_url', data.moodleUrl);
    formData.append('moodle_token', data.moodleToken);
    formData.append('course_ids', JSON.stringify(data.courseIds));

    if (data.files && data.files.length > 0) {
      data.files.forEach((file) => {
        formData.append('files', file);
      });
    }

    if (data.textEntries?.length) {
      formData.append('text_entries', JSON.stringify(data.textEntries));
    }

    if (data.forceOcr) {
      formData.append('force_ocr', 'true');
    }

    return this.http.post<ChatbotItem>(
      `${this.baseUrl}/create-from-moodle`,
      formData
    );
  }

  updateChatbot(
    id: string,
    updates: Partial<ChatbotItem>
  ): Observable<ChatbotItem> {
    return this.http.patch<ChatbotItem>(`${this.baseUrl}/${id}`, updates);
  }

  deleteChatbot(id: string): Observable<DeleteChatbotResponse> {
    return this.http.delete<DeleteChatbotResponse>(`${this.baseUrl}/${id}`);
  }

  rotateChatbotToken(id: string): Observable<ChatbotItem> {
    return this.http.post<ChatbotItem>(
      `${this.baseUrl}/${id}/rotate-token`,
      {}
    );
  }

  synchronizeChatbot(id: string): Observable<{ job_id?: string; [key: string]: any }> {
    return this.http.post<{ job_id?: string; [key: string]: any }>(`${this.baseUrl}/${id}/reindex`, {});
  }

  getReindexSchedule(id: string): Observable<ReindexSchedule> {
    return this.http.get<ReindexSchedule>(
      `${this.baseUrl}/${id}/reindex-schedule`
    );
  }

  setReindexSchedule(
    id: string,
    payload: Omit<ReindexSchedule, 'chatbot_id'>
  ): Observable<ReindexSchedule> {
    return this.http.put<ReindexSchedule>(
      `${this.baseUrl}/${id}/reindex-schedule`,
      payload
    );
  }

  deleteReindexSchedule(id: string): Observable<ReindexSchedule> {
    return this.http.delete<ReindexSchedule>(
      `${this.baseUrl}/${id}/reindex-schedule`
    );
  }

  cancelIndexing(chatbotId: string): Observable<{ message: string; chatbot_id: string; status: string }> {
    return this.http.post<{ message: string; chatbot_id: string; status: string }>(
      `${this.baseUrl}/${chatbotId}/cancel-indexing`,
      {}
    );
  }

  getJobStatus(chatbotId: string): Observable<JobStatusResponse> {
    return this.http.get<JobStatusResponse>(`${this.baseUrl}/${chatbotId}/job-status`);
  }

  listFiles(chatbotId: string): Observable<ChatbotFilesResponse> {
    return this.http.get<ChatbotFilesResponse>(
      `${this.baseUrl}/${chatbotId}/files`
    );
  }

  uploadFiles(chatbotId: string, files: File[]): Observable<ChatbotFile[]> {
    const formData = new FormData();
    files.forEach((file) => {
      formData.append('files', file);
    });

    return this.http.post<ChatbotFile[]>(
      `${this.baseUrl}/${chatbotId}/add-files`,
      formData
    );
  }

  deleteFile(chatbotId: string, fileId: string): Observable<void> {
    return this.http.delete<void>(
      `${this.baseUrl}/${chatbotId}/files/${fileId}`
    );
  }

  getFileDownloadPath(chatbotId: string, fileId: string): string {
    return `${this.baseUrl}/${chatbotId}/files/${fileId}/download`;
  }

  getFileParsedContent(
    chatbotId: string,
    fileId: string
  ): Observable<FileParsedContent> {
    return this.http.get<FileParsedContent>(
      `${this.baseUrl}/${chatbotId}/files/${fileId}/parsed-content`
    );
  }

  getTextEntry(
    chatbotId: string,
    fileId: string
  ): Observable<TextEntryContentResponse> {
    return this.http.get<TextEntryContentResponse>(
      `${this.baseUrl}/${chatbotId}/files/${fileId}/text`
    );
  }

  uploadAvatar(chatbotId: string, file: File): Observable<ChatbotItem> {
    const formData = new FormData();
    formData.append('file', file);
    return this.http.post<ChatbotItem>(
      `${this.baseUrl}/${chatbotId}/avatar`,
      formData
    );
  }

  deleteAvatar(chatbotId: string): Observable<ChatbotItem> {
    return this.http.delete<ChatbotItem>(
      `${this.baseUrl}/${chatbotId}/avatar`
    );
  }

  uploadHeaderLogo(chatbotId: string, file: File): Observable<ChatbotItem> {
    const formData = new FormData();
    formData.append('file', file);
    return this.http.post<ChatbotItem>(
      `${this.baseUrl}/${chatbotId}/header-logo`,
      formData
    );
  }

  deleteHeaderLogo(chatbotId: string): Observable<ChatbotItem> {
    return this.http.delete<ChatbotItem>(
      `${this.baseUrl}/${chatbotId}/header-logo`
    );
  }

  updateFiles(
    chatbotId: string,
    filesToAdd: File[],
    fileIdsToDelete: string[],
    textEntries: StagedTextEntryPayload[] = []
  ): Observable<UpdateFilesResponse> {
    const formData = new FormData();

    filesToAdd.forEach((file) => {
      formData.append('files', file);
    });

    formData.append('file_ids_to_delete', JSON.stringify(fileIdsToDelete));

    if (textEntries.length > 0) {
      formData.append('text_entries', JSON.stringify(textEntries));
    }

    return this.http.patch<UpdateFilesResponse>(
      `${this.baseUrl}/${chatbotId}/files`,
      formData
    );
  }
}
