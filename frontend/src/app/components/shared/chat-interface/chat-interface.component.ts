import {
  Component,
  signal,
  input,
  computed,
  effect,
  ChangeDetectionStrategy,
  ViewChild,
  ElementRef,
  ChangeDetectorRef,
  inject,
} from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { TranslatePipe } from '@ngx-translate/core';
import { environment } from '../../../../environments/environment';
import { MarkdownComponent } from 'ngx-markdown';
import { ChatbotPersonaType } from '../../../interfaces/chatbot-i';
import { LanguageSelectorComponent } from '../components/language-selector/language-selector.component';
import { MlangPipe } from '../../../core/mlang.pipe';

interface Citation {
  id: number;
  file_name: string;
  file_id: string | null;
  source_url?: string | null;
  score: number | null;
}

interface GroupedCitation {
  ids: number[];
  file_name: string;
  file_id: string | null;
  source_url?: string | null;
}

interface ChatMessage {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  timestamp: Date;
  citations?: Citation[];
}

@Component({
  selector: 'app-chat-interface',
  imports: [CommonModule, FormsModule, TranslatePipe, MarkdownComponent, LanguageSelectorComponent, MlangPipe],
  template: `
    <div class="chat-interface" [class.compact]="compact()">
      @if (!compact()) {
      <div class="chat-header">
        <img src="/icons/alice_logo.svg" alt="Alice" class="chat-header-logo" height="32" />
        <div class="chat-header-info">
          <h1 class="chat-title">{{ chatbotName() }}</h1>
        </div>
        <button
          type="button"
          class="clear-chat-btn"
          (click)="onClearMessages()"
          [disabled]="isLoading() || messages().length === 0"
          [attr.aria-label]="'chat.clearConversation' | translate"
          [title]="'chat.clearConversation' | translate"
        >
          <img src="/icons/trash.svg" alt="" width="18" height="18" />
        </button>
        <app-language-selector></app-language-selector>
      </div>
      }

      <div class="chat-messages" #messagesContainer>
        @if (messages().length === 0) {
        <div class="chat-empty-state">
          @if (!hasCustomAvatar()) {
          <img [src]="effectiveAvatarUrl()" alt="Chat" />
          }
          <h3>{{ 'chat.startConversation' | translate }}</h3>
          <p>{{ 'chat.askAnything' | translate }}</p>
          @if (promptSuggestions().length) {
          <div class="prompt-suggestions">
            @for (suggestion of promptSuggestions(); track suggestion) {
            <button class="suggestion-chip" (click)="useSuggestion(suggestion)">
              {{ suggestion }}
            </button>
            }
          </div>
          }
        </div>
        } @else {
        <div class="messages-list">
          @for (message of messages(); track message.id) {
          <div class="message" [class]="'message-' + message.role">
            @if (message.role === 'assistant') {
            <div class="message-avatar" [class.has-custom-avatar]="hasCustomAvatar()">
              <img
                [src]="effectiveAvatarUrl()"
                alt="Assistant"
                width="24"
                height="24"
              />
            </div>
            }
            <div class="message-content">
              <markdown
                class="variable-binding message-text"
                [data]="formatCitations(message.content)"
              ></markdown>
              @if (message.citations?.length) {
              <div class="citations-list">
                @for (group of groupCitations(message.citations!, message.content); track group.file_name) {
                <a
                  class="citation-item"
                  [href]="getCitationUrl(group)"
                  target="_blank"
                  rel="noopener"
                  [title]="group.file_name | mlang"
                >
                  @for (id of group.ids; track id) {
                  <span class="citation-number">{{ id }}</span>
                  }
                  <span class="citation-filename">{{ group.file_name | mlang }}</span>
                </a>
                }
              </div>
              }
              <div class="message-timestamp">
                {{ message.timestamp | date : 'short' }}
              </div>
            </div>
            @if (message.role === 'user') {
            <div class="message-avatar user">
              <img src="/icons/user_yellow.png" alt="User" />
            </div>
            }
          </div>
          } @if (showTypingIndicator()) {
          <div class="message message-assistant">
            <div class="message-avatar" [class.has-custom-avatar]="hasCustomAvatar()">
              <img [src]="effectiveAvatarUrl()" alt="Assistant" />
            </div>
            <div class="message-content">
              <div class="message-typing">
                <span></span>
                <span></span>
                <span></span>
              </div>
            </div>
          </div>
          }
        </div>
        }
      </div>

      <div class="chat-input-container" [class.focus]="isInputFocused()">
        <div class="chat-input-wrapper">
          <textarea
            class="chat-input"
            [(ngModel)]="userInput"
            (keypress)="handleKeyPress($event)"
            (focus)="isInputFocused.set(true)"
            (blur)="isInputFocused.set(false)"
            [placeholder]="'chat.typeMessage' | translate"
            [disabled]="isLoading()"
            rows="1"
          ></textarea>
          <button
            class="btn btn-primary btn-send"
            (click)="sendMessage()"
            [disabled]="!userInput().trim() || isLoading()"
            type="button"
            aria-label="Send message"
          >
            <img
              src="/icons/arrow-right.svg"
              alt="Send"
              width="20"
              height="20"
            />
          </button>
        </div>
      </div>
      <p class="disclaimer">
        {{ 'chat.aiDisclaimer' | translate }}
      </p>
    </div>
  `,
  styleUrl: './chat-interface.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class ChatInterfaceComponent {
  private cdr = inject(ChangeDetectorRef);
  @ViewChild('messagesContainer') private messagesContainer!: ElementRef;

  // Bumps when the on-disk message schema changes, discard older payloads.
  private static readonly STORAGE_VERSION = 1;
  private historyLoaded = false;

  constructor() {
    effect(() => {
      const id = this.chatbotId();
      if (!id) return;
      if (!this.persistSession()) {
        // Drop any history written under a previous "persist on" setting.
        try { localStorage.removeItem(this.storageKey(id)); } catch {}
        return;
      }
      if (this.compact() || this.historyLoaded) return;
      this.historyLoaded = true;
      this.loadMessagesFromStorage(id);
    });

    effect(() => {
      const msgs = this.messages();
      const id = this.chatbotId();
      if (!id || this.compact() || !this.persistSession() || !this.historyLoaded) {
        return;
      }
      if (this.isLoading()) return;
      this.saveMessagesToStorage(id, msgs);
    });
  }

  private storageKey(id: string): string {
    return `chatbot_${id}_messages`;
  }

  private loadMessagesFromStorage(id: string): void {
    try {
      const raw = localStorage.getItem(this.storageKey(id));
      if (!raw) return;
      const parsed = JSON.parse(raw) as {
        version: number;
        messages: ChatMessage[];
      };
      if (parsed?.version !== ChatInterfaceComponent.STORAGE_VERSION) return;
      const revived = parsed.messages.map((m) => ({
        ...m,
        timestamp: new Date(m.timestamp),
      }));
      this.messages.set(revived);
    } catch (err) {
      console.warn('Failed to load chat history:', err);
    }
  }

  private saveMessagesToStorage(id: string, msgs: ChatMessage[]): void {
    try {
      if (msgs.length === 0) {
        localStorage.removeItem(this.storageKey(id));
        return;
      }
      const payload = {
        version: ChatInterfaceComponent.STORAGE_VERSION,
        messages: msgs,
      };
      localStorage.setItem(this.storageKey(id), JSON.stringify(payload));
    } catch (err) {
      console.warn('Failed to save chat history:', err);
    }
  }

  onClearMessages(): void {
    this.messages.set([]);
    this.currentAssistantMessageId = null;
    try {
      localStorage.removeItem(this.storageKey(this.chatbotId()));
    } catch (err) {
      console.warn('Failed to clear chat history:', err);
    }
  }

  chatbotId = input.required<string>();
  chatbotName = input<string>('AI Assistant');
  compact = input<boolean>(false);
  chatbotPassword = input<string | null>(null);
  personaType = input<ChatbotPersonaType>('teacher');
  promptSuggestions = input<string[]>([]);
  // Falls back to the persona's bundled avatar when null/undefined.
  avatarUrl = input<string | null>(null);
  // When false, conversation is in-memory only and wiped on reload.
  persistSession = input<boolean>(false);

  private personaAvatarUrl = computed(() => {
    switch (this.personaType()) {
      case 'teacher':
        return '/icons/avatar1.png';
      case 'studycompanion':
        return '/icons/avatar2.png';
      case 'custom':
        return '/icons/avatar3.png';
      default:
        return '/icons/avatar1.png';
    }
  });

  effectiveAvatarUrl = computed(
    () => this.avatarUrl() ?? this.personaAvatarUrl(),
  );

  // Custom uploads are square photos (cover-cropped); persona PNGs are
  // tall portraits that need oversize-and-offset framing.
  hasCustomAvatar = computed(() => !!this.avatarUrl());

  messages = signal<ChatMessage[]>([]);
  userInput = signal<string>('');
  isLoading = signal<boolean>(false);
  isInputFocused = signal<boolean>(false);

  private currentAssistantMessageId: string | null = null;

  hasStreamingMessage = computed(() => {
    const msgs = this.messages();
    if (msgs.length === 0) return false;
    const lastMessage = msgs[msgs.length - 1];
    return lastMessage.role === 'assistant' && this.isLoading();
  });

  showTypingIndicator = computed(() => {
    return this.isLoading() && !this.hasStreamingMessage();
  });


  // Renumber citations to sequential display ids based on first appearance,
  // so [1] and [5] render as [1] and [2] without visible gaps.
  private buildCitationRemap(content: string): Map<number, number> {
    const remap = new Map<number, number>();
    const regex = /(?:\[(\d+)\](?!\())|(?:【(\d+)】)/g;
    let counter = 1;
    let match: RegExpExecArray | null;
    while ((match = regex.exec(content)) !== null) {
      const originalId = parseInt(match[1] || match[2], 10);
      if (!remap.has(originalId)) {
        remap.set(originalId, counter++);
      }
    }
    return remap;
  }

  formatCitations(content: string): string {
    const remap = this.buildCitationRemap(content);
    return content.replace(/(?:\[(\d+)\](?!\())|(?:【(\d+)】)/g, (_, n1, n2) => {
      const originalId = parseInt(n1 || n2, 10);
      const displayId = remap.get(originalId) ?? originalId;
      return `<sup class="inline-citation">${displayId}</sup>`;
    });
  }

  groupCitations(citations: Citation[], content: string): GroupedCitation[] {
    const remap = this.buildCitationRemap(content);
    const sorted = [...citations].sort(
      (a, b) => (remap.get(a.id) ?? a.id) - (remap.get(b.id) ?? b.id),
    );
    const groups = new Map<string, GroupedCitation>();
    for (const cite of sorted) {
      const key = cite.file_id || cite.file_name;
      const displayId = remap.get(cite.id) ?? cite.id;
      const existing = groups.get(key);
      if (existing) {
        existing.ids.push(displayId);
      } else {
        groups.set(key, {
          ids: [displayId],
          file_name: cite.file_name,
          file_id: cite.file_id,
          source_url: cite.source_url,
        });
      }
    }
    return Array.from(groups.values());
  }

  getPreviewUrlByFileId(fileId: string | null): string {
    if (!fileId) return '#';
    const chatbotId = this.chatbotId();
    const password = this.chatbotPassword();
    const passwordParam = password ? `?password=${encodeURIComponent(password)}` : '';
    return `${environment.apiBaseUrl}/chatbots/${chatbotId}/files/${fileId}/preview${passwordParam}`;
  }

  getCitationUrl(group: GroupedCitation): string {
    if (group.source_url) return group.source_url;
    return this.getPreviewUrlByFileId(group.file_id);
  }

  private scrollToBottom(): void {
    this.cdr.detectChanges();
    requestAnimationFrame(() => {
      try {
        const container = this.messagesContainer?.nativeElement;
        if (container) {
          container.scrollTo({
            top: container.scrollHeight,
            behavior: 'smooth',
          });
        }
      } catch (err) {
        console.error('Error scrolling to bottom:', err);
      }
    });
  }

  useSuggestion(text: string): void {
    this.userInput.set(text);
    this.sendMessage();
  }

  sendMessage(): void {
    const input = this.userInput().trim();
    if (!input || this.isLoading()) return;

    const userMessage: ChatMessage = {
      id: `user-${Date.now()}`,
      role: 'user',
      content: input,
      timestamp: new Date(),
    };

    this.messages.update((msgs) => [...msgs, userMessage]);
    this.userInput.set('');
    this.isLoading.set(true);
    this.scrollToBottom();

    const apiMessages = this.messages().map((msg) => ({
      role: msg.role,
      content: msg.content,
    }));

    this.currentAssistantMessageId = `assistant-${Date.now()}`;
    this.streamChatResponse(apiMessages);
  }

  private async streamChatResponse(
    messages: Array<{ role: string; content: string }>
  ): Promise<void> {
    try {
      const chatbotId = this.chatbotId();
      const url = `${environment.apiBaseUrl}/chatbots/${chatbotId}/chat/stream`;
      const password = this.chatbotPassword();
      const requestBody = password ? { messages, password } : { messages };

      const response = await fetch(url, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify(requestBody),
      });

      if (!response.ok) {
        throw new Error(`HTTP error! status: ${response.status}`);
      }

      const reader = response.body?.getReader();
      const decoder = new TextDecoder();

      if (!reader) {
        throw new Error('No response body');
      }

      let buffer = '';

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split('\n');
        buffer = lines.pop() || '';

        for (const line of lines) {
          if (line.startsWith('data: ')) {
            const data = line.slice(6);
            try {
              const parsed = JSON.parse(data);

              if (parsed.citations) {
                this.setCitationsOnAssistantMessage(parsed.citations);
                this.scrollToBottom();
                continue;
              }

              if (parsed.choices?.[0]?.delta?.content) {
                this.appendToAssistantMessage(parsed.choices[0].delta.content);
                this.scrollToBottom();
              }
              if (parsed.choices?.[0]?.finish_reason === 'stop') {
                this.isLoading.set(false);
              }
            } catch (e) {
              console.error('Error parsing SSE data:', e);
            }
          }
        }
      }

      this.isLoading.set(false);
    } catch (error) {
      console.error('Error streaming chat response:', error);
      if (this.currentAssistantMessageId) {
        this.updateAssistantMessage(
          'Sorry, there was an error processing your request. Please try again.'
        );
      }
      this.isLoading.set(false);
    }
  }

  private setCitationsOnAssistantMessage(citations: Citation[]): void {
    if (!this.currentAssistantMessageId) return;

    this.messages.update((msgs) =>
      msgs.map((msg) =>
        msg.id === this.currentAssistantMessageId
          ? { ...msg, citations }
          : msg
      )
    );
  }

  private updateAssistantMessage(content: string): void {
    if (!this.currentAssistantMessageId) return;

    const existingMessageIndex = this.messages().findIndex(
      (msg) => msg.id === this.currentAssistantMessageId
    );

    if (existingMessageIndex >= 0) {
      this.messages.update((msgs) =>
        msgs.map((msg) =>
          msg.id === this.currentAssistantMessageId ? { ...msg, content } : msg
        )
      );
    } else {
      const assistantMessage: ChatMessage = {
        id: this.currentAssistantMessageId,
        role: 'assistant',
        content,
        timestamp: new Date(),
      };
      this.messages.update((msgs) => [...msgs, assistantMessage]);
    }
    this.scrollToBottom();
  }

  private appendToAssistantMessage(contentChunk: string): void {
    if (!this.currentAssistantMessageId) return;

    const existingMessage = this.messages().find(
      (msg) => msg.id === this.currentAssistantMessageId
    );

    if (existingMessage) {
      this.messages.update((msgs) =>
        msgs.map((msg) =>
          msg.id === this.currentAssistantMessageId
            ? { ...msg, content: msg.content + contentChunk }
            : msg
        )
      );
    } else {
      const assistantMessage: ChatMessage = {
        id: this.currentAssistantMessageId,
        role: 'assistant',
        content: contentChunk,
        timestamp: new Date(),
      };
      this.messages.update((msgs) => [...msgs, assistantMessage]);
    }
  }

  handleKeyPress(event: KeyboardEvent): void {
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault();
      this.sendMessage();
    }
  }
}
