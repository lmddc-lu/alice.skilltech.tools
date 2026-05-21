import { HttpClient } from '@angular/common/http';
import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  OnInit,
  Renderer2,
  computed,
  effect,
  inject,
  signal,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { TranslatePipe, TranslateService } from '@ngx-translate/core';
import { ChatbotI, ChatbotItem, ChatbotStatus } from '../../../../interfaces/chatbot-i';
import { RouterLink } from '@angular/router';
import { ChatbotService } from '../../../../services/chatbot/chatbot.service';
import { DatePipe } from '@angular/common';

@Component({
  selector: 'app-chatbot-list',
  imports: [TranslatePipe, RouterLink, DatePipe],
  templateUrl: './chatbot-list.component.html',
  styleUrl: './chatbot-list.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class ChatbotListComponent implements OnInit {
  private http = inject(HttpClient);
  private chatbotService = inject(ChatbotService);
  private renderer = inject(Renderer2);
  private translate = inject(TranslateService);
  private destroyRef = inject(DestroyRef);

  readonly ChatbotStatus = ChatbotStatus;

  private static readonly POLL_INTERVAL_MS = 10_000;

  fakeChatbots: ChatbotItem[] = [];
  chatbots = signal<ChatbotI[]>([]);
  loading = signal(true);
  error = signal<string | null>(null);

  isEmpty = computed(
    () => !this.loading() && this.chatbots().length === 0
  );

  hasProcessing = computed(() =>
    this.chatbots().some((cb) => cb.status === ChatbotStatus.PROCESSING)
  );

  constructor() {
    effect((onCleanup) => {
      if (this.isEmpty()) {
        this.renderer.addClass(document.body, 'no-chatbots');
      } else {
        this.renderer.removeClass(document.body, 'no-chatbots');
      }
      onCleanup(() =>
        this.renderer.removeClass(document.body, 'no-chatbots')
      );
    });

    effect((onCleanup) => {
      if (!this.hasProcessing()) return;
      const id = setInterval(
        () => this.refreshChatbots(),
        ChatbotListComponent.POLL_INTERVAL_MS
      );
      onCleanup(() => clearInterval(id));
    });
  }

  ngOnInit(): void {
    this.loadChatbots();

    this.http
      .get<ChatbotItem[]>('chatbots.json')
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe((data) => {
        this.fakeChatbots = data;
      });
  }

  private loadChatbots(): void {
    this.chatbotService
      .getChatbots()
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (chatbots: ChatbotI[]) => {
          this.chatbots.set(chatbots);
          this.loading.set(false);
        },
        error: (err) => {
          this.error.set(this.translate.instant('chatbots.loadError'));
          this.loading.set(false);
          console.error('Error loading chatbots:', err);
        },
      });
  }

  private refreshChatbots(): void {
    this.chatbotService.getChatbots().subscribe({
      next: (chatbots: ChatbotI[]) => this.chatbots.set(chatbots),
      error: (err) => console.error('Error polling chatbot status:', err),
    });
  }
}
