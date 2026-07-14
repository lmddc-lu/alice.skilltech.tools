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
import { TranslatePipe, TranslateService } from '@ngx-translate/core';
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

// Full retrieved chunk, only sent to chatbot owners / platform admins for
// debugging retrieval quality. Shown in a collapsible per-message panel.
interface DebugChunk {
  id: number;
  content: string;
  score: number | null;
  document_id?: string | null;
  file_name: string;
  file_id: string | null;
  source_url?: string | null;
  chunk_index?: number | null;
  total_chunks?: number | null;
  headings?: string[];
}

interface ChatMessage {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  timestamp: Date;
  citations?: Citation[];
  debugChunks?: DebugChunk[];
}

@Component({
  selector: 'app-chat-interface',
  imports: [CommonModule, FormsModule, TranslatePipe, MarkdownComponent, LanguageSelectorComponent, MlangPipe],
  template: `
    <div
      class="chat-interface"
      [class.compact]="compact()"
      [style.--primary-color]="accentColor() || null"
    >
      @if (!compact()) {
      <div class="chat-header">
        <img
          [src]="effectiveHeaderLogoUrl()"
          alt="Alice"
          class="chat-header-logo"
          height="32"
        />
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
          <img
            [src]="effectiveAvatarUrl()"
            alt="Chat"
            [class.has-custom-avatar]="hasCustomAvatar()"
          />
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
                katex
                [mermaid]="renderMermaidFor(message)"
                [data]="formatCitations(message.content)"
              ></markdown>
              @if (message.citations?.length) {
              <div class="citations-list">
                @for (group of groupCitations(message.citations!, message.content); track group.file_name) {
                <a
                  class="citation-item"
                  [href]="getCitationUrl(group)"
                  [attr.target]="citationTarget()"
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
              @if (message.debugChunks?.length) {
              <div class="debug-chunks" [class.open]="isDebugChunksOpen(message.id)">
                <button
                  type="button"
                  class="debug-chunks-toggle"
                  (click)="toggleDebugChunks(message.id)"
                  [title]="'chat.retrievedChunks' | translate"
                  [attr.aria-label]="'chat.retrievedChunks' | translate"
                  [attr.aria-expanded]="isDebugChunksOpen(message.id)"
                >
                  <span class="debug-chunks-caret">{{
                    isDebugChunksOpen(message.id) ? '▾' : '▸'
                  }}</span>
                  {{ message.debugChunks!.length }}
                </button>
                @if (isDebugChunksOpen(message.id)) {
                <div class="debug-chunks-list">
                  @for (chunk of message.debugChunks!; track chunk.id) {
                  <div class="debug-chunk">
                    <div class="debug-chunk-header">
                      <span class="debug-chunk-id">#{{ chunk.id }}</span>
                      <span class="debug-chunk-file">{{ chunk.file_name | mlang }}</span>
                      @if (chunk.chunk_index != null) {
                      <span class="debug-chunk-pos"
                        >chunk {{ chunk.chunk_index
                        }}@if (chunk.total_chunks != null) {/{{ chunk.total_chunks }}}</span
                      >
                      }
                      @if (chunk.score != null) {
                      <span class="debug-chunk-score"
                        >score {{ chunk.score | number : '1.3-3' }}</span
                      >
                      }
                    </div>
                    @if (chunk.headings?.length) {
                    <div class="debug-chunk-headings">
                      {{ chunk.headings!.join(' › ') }}
                    </div>
                    }
                    <pre class="debug-chunk-content">{{ chunk.content }}</pre>
                  </div>
                  }
                </div>
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
          } @if (showSearchingIndicator() || showThinkingIndicator()) {
          <div class="message message-assistant">
            <div class="message-avatar" [class.has-custom-avatar]="hasCustomAvatar()">
              <img [src]="effectiveAvatarUrl()" alt="Assistant" />
            </div>
            <div class="message-content">
              @if (showSearchingIndicator()) {
              <div class="message-thinking" role="status" [attr.aria-label]="'chat.searching' | translate">
                <img src="/icons/search.svg" alt="" class="thinking-icon" width="16" height="16" />
                <span class="thinking-label">{{ 'chat.searching' | translate }}</span>
              </div>
              } @else {
              <div class="message-thinking" role="status" [attr.aria-label]="'chat.thinking' | translate">
                <img src="/icons/stars_yellow.svg" alt="" class="thinking-icon" width="16" height="16" />
                <span class="thinking-label">{{ 'chat.thinking' | translate }}</span>
              </div>
              }
            </div>
          </div>
          }
        </div>
        }
      </div>

      @if (piiFiltered() && !piiWarningDismissed()) {
      <div class="pii-warning" role="status">
        <span class="pii-warning-icon" aria-hidden="true"></span>
        <span class="pii-warning-text">{{ 'chat.piiFilterWarning' | translate }}</span>
        <button
          type="button"
          class="pii-warning-dismiss"
          (click)="dismissPiiWarning()"
          [attr.aria-label]="'chat.dismiss' | translate"
        >
          ✕
        </button>
      </div>
      }

      <div class="chat-input-container" [class.focus]="isInputFocused()">
        <div class="chat-input-wrapper">
          <textarea
            class="chat-input"
            [(ngModel)]="userInput"
            (keypress)="handleKeyPress($event)"
            (focus)="isInputFocused.set(true)"
            (blur)="isInputFocused.set(false)"
            [placeholder]="'chat.typeMessage' | translate"
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
  private translate = inject(TranslateService);
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

    // Lazy-load mermaid the first time a finalized message contains a diagram.
    effect(() => {
      if (this.mermaidLoaded()) return;
      const needsMermaid = this.messages().some(
        (m) => !this.isMessageStreaming(m) && m.content.includes('```mermaid')
      );
      if (needsMermaid) this.ensureMermaid();
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
      // Jump to the latest message after restoring history on reload.
      this.scrollToBottom('auto');
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
        // Debug chunks are transient owner/admin-only data; never persist them.
        messages: msgs.map(({ debugChunks, ...rest }) => rest),
      };
      localStorage.setItem(this.storageKey(id), JSON.stringify(payload));
    } catch (err) {
      console.warn('Failed to save chat history:', err);
    }
  }

  onClearMessages(): void {
    this.messages.set([]);
    this.currentAssistantMessageId = null;
    this.piiFiltered.set(false);
    this.piiWarningDismissed.set(false);
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
  // Instance-admin branding. Null values fall back to the default look.
  accentColor = input<string | null>(null);
  headerLogoUrl = input<string | null>(null);
  // When false, conversation is in-memory only and wiped on reload.
  persistSession = input<boolean>(false);
  // Where citation links open. '_parent' breaks out of an iframe to the host
  // page; '_blank' (default) opens a new tab.
  citationTarget = input<string>('_blank');
  // Opt-in to the owner/admin retrieved-chunks debug panel. Only the editor's
  // preview window enables it; the backend still verifies owner/admin rights.
  showDebugChunks = input<boolean>(false);

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

  // Falls back to the default product logo when no custom header logo is set.
  effectiveHeaderLogoUrl = computed(
    () => this.headerLogoUrl() ?? '/icons/alice_logo.svg',
  );

  // Custom uploads are square photos (cover-cropped); persona PNGs are
  // tall portraits that need oversize-and-offset framing.
  hasCustomAvatar = computed(() => !!this.avatarUrl());

  messages = signal<ChatMessage[]>([]);
  userInput = signal<string>('');
  isLoading = signal<boolean>(false);
  // Flips true once the first stream chunk arrives (even an empty content
  // delta). Separates the pre-stream phase (request sent, server retrieving)
  // from the thinking phase (model generating, empty deltas streaming).
  streamStarted = signal<boolean>(false);
  isInputFocused = signal<boolean>(false);
  // True once the PII filter has actually stripped personal data from a message
  // in this conversation; drives the "don't share personal info" warning.
  piiFiltered = signal<boolean>(false);
  piiWarningDismissed = signal<boolean>(false);

  private currentAssistantMessageId: string | null = null;

  // Mermaid ships a 3.6MB bundle, so it is dynamically imported and attached to
  // the global scope only once a finalized message actually contains a diagram
  // (ngx-markdown's renderMermaid reads a global `mermaid`).
  mermaidLoaded = signal<boolean>(false);
  private mermaidLoading = false;

  private async ensureMermaid(): Promise<void> {
    if (this.mermaidLoaded() || this.mermaidLoading) return;
    this.mermaidLoading = true;
    const mermaid = (await import('mermaid')).default;
    (globalThis as { mermaid?: unknown }).mermaid = mermaid;
    this.mermaidLoaded.set(true);
  }

  // A message is still streaming while it is the last one and a response is
  // being generated. Mermaid must not run on a partial diagram (it throws), so
  // rendering is gated until the message is finalized.
  isMessageStreaming(message: ChatMessage): boolean {
    const msgs = this.messages();
    return (
      this.isLoading() &&
      message.role === 'assistant' &&
      msgs.length > 0 &&
      msgs[msgs.length - 1].id === message.id
    );
  }

  renderMermaidFor(message: ChatMessage): boolean {
    return this.mermaidLoaded() && !this.isMessageStreaming(message);
  }

  // Message ids whose retrieved-chunks debug panel is expanded.
  private expandedDebug = signal<Set<string>>(new Set());

  isDebugChunksOpen(messageId: string): boolean {
    return this.expandedDebug().has(messageId);
  }

  toggleDebugChunks(messageId: string): void {
    this.expandedDebug.update((open) => {
      const next = new Set(open);
      if (next.has(messageId)) {
        next.delete(messageId);
      } else {
        next.add(messageId);
      }
      return next;
    });
  }

  hasStreamingMessage = computed(() => {
    const msgs = this.messages();
    if (msgs.length === 0) return false;
    const lastMessage = msgs[msgs.length - 1];
    return lastMessage.role === 'assistant' && this.isLoading();
  });

  // Request sent, but no stream chunk has arrived yet: the server is
  // retrieving context (embed query, Qdrant search, prompt build).
  showSearchingIndicator = computed(() => {
    return this.isLoading() && !this.streamStarted();
  });

  // Stream has started (chunks arriving) but no answer token yet: the model
  // is reasoning, emitting empty content deltas.
  showThinkingIndicator = computed(() => {
    return (
      this.isLoading() && this.streamStarted() && !this.hasStreamingMessage()
    );
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

  // KaTeX math spans ($$...$$ and $...$). Citation markup must never be
  // injected inside these, or the HTML corrupts the LaTeX passed to KaTeX.
  private static readonly MATH_SPAN_RE =
    /(\$\$[\s\S]*?\$\$|\$(?:\\.|[^$\\\n])*?\$)/g;
  // CJK citation brackets never occur in valid LaTeX, so they can be dropped
  // from inside a formula; [n] optional args (e.g. \sqrt[3]) are left intact.
  private static readonly MATH_CITATION_RE = /【\d+】/g;
  // A citation flush against a closing $$/$ places its <sup> badge directly
  // after the delimiter, which breaks marked-katex's closing rule (it requires
  // whitespace, punctuation, or end-of-string after the delimiter). A leading
  // space on the following segment keeps the formula recognizable as math.
  private static readonly LEADING_CITATION_RE = /^(?:\[\d+\](?!\()|【\d+】)/;

  formatCitations(content: string): string {
    const remap = this.buildCitationRemap(content);
    const toBadges = (text: string): string =>
      text.replace(/(?:\[(\d+)\](?!\())|(?:【(\d+)】)/g, (_, n1, n2) => {
        const originalId = parseInt(n1 || n2, 10);
        const displayId = remap.get(originalId) ?? originalId;
        return `<sup class="inline-citation">${displayId}</sup>`;
      });
    // Split on math spans: even segments are text (citations -> badges), odd
    // segments are the math spans themselves (kept verbatim, CJK markers dropped).
    return content
      .split(ChatInterfaceComponent.MATH_SPAN_RE)
      .map((part, i) => {
        if (i % 2 === 1) {
          return part.replace(ChatInterfaceComponent.MATH_CITATION_RE, '');
        }
        // Text segments after index 0 immediately follow a math span. If one
        // starts with a citation, insert a space so the preceding delimiter is
        // followed by whitespace and the formula still renders.
        const needsSpace =
          i > 0 && ChatInterfaceComponent.LEADING_CITATION_RE.test(part);
        return (needsSpace ? ' ' : '') + toBadges(part);
      })
      .join('');
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

  private scrollToBottom(behavior: ScrollBehavior = 'smooth'): void {
    this.cdr.detectChanges();
    requestAnimationFrame(() => {
      try {
        const container = this.messagesContainer?.nativeElement;
        if (container) {
          container.scrollTo({
            top: container.scrollHeight,
            behavior,
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
    this.streamStarted.set(false);
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
      const requestBody: {
        messages: Array<{ role: string; content: string }>;
        password?: string;
        debug?: boolean;
      } = { messages };
      if (password) requestBody.password = password;
      if (this.showDebugChunks()) requestBody.debug = true;

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

              if (parsed.pii_filtered) {
                this.piiFiltered.set(true);
                continue;
              }

              if (parsed.citations) {
                this.setCitationsOnAssistantMessage(parsed.citations);
                this.scrollToBottom();
                continue;
              }

              // Owner/admin-only: full retrieved chunks for debugging retrieval.
              if (parsed.debug_chunks) {
                this.setDebugChunksOnAssistantMessage(parsed.debug_chunks);
                continue;
              }

              // Any delta chunk, including the empty content deltas emitted
              // while the model reasons means generation has begun. Flip out
              // of the "searching" phase into the "thinking" phase.
              if (parsed.choices?.[0]?.delta) {
                this.streamStarted.set(true);
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
          this.translate.instant('chat.errorProcessing')
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

  private setDebugChunksOnAssistantMessage(debugChunks: DebugChunk[]): void {
    if (!this.currentAssistantMessageId) return;

    this.messages.update((msgs) =>
      msgs.map((msg) =>
        msg.id === this.currentAssistantMessageId
          ? { ...msg, debugChunks }
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

  dismissPiiWarning(): void {
    this.piiWarningDismissed.set(true);
  }

  handleKeyPress(event: KeyboardEvent): void {
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault();
      this.sendMessage();
    }
  }
}
