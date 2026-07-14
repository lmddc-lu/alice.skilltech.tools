import {
  Component,
  signal,
  inject,
  OnInit,
  computed,
  ChangeDetectionStrategy,
} from '@angular/core';

import { ActivatedRoute, Router } from '@angular/router';
import { ChatInterfaceComponent } from '../../shared/chat-interface/chat-interface.component';
import {
  ChatAccessDialogComponent,
  AccessDialogType,
} from '../../shared/components/chat-access-dialog/chat-access-dialog.component';
import { ChatbotService } from '../../../services/chatbot/chatbot.service';
import { AuthService } from '../../../services/core/auth.service';
import {
  ChatbotAccessLevel,
  ChatbotInfoResponse,
  ChatbotPublicInfo,
  ChatbotStatus,
} from '../../../interfaces/chatbot-i';

@Component({
  selector: 'app-chat',
  standalone: true,
  imports: [ChatInterfaceComponent, ChatAccessDialogComponent],
  template: `
    <div class="chat-page">
      @if (showAccessDialog()) {
      <app-chat-access-dialog
        [dialogType]="accessDialogType()"
        [errorMessage]="errorMessage()"
        [passwordError]="passwordError()"
        [isSubmitting]="submittingPassword()"
        (submitPassword)="onSubmitPassword($event)"
        (cancel)="onCancel()"
        (login)="onLogin()"
      />
      } @else if (chatbotId() && chatbotData()) {
      <app-chat-interface
        [chatbotId]="chatbotId()"
        [chatbotName]="chatbotName()"
        [chatbotPassword]="chatbotPassword()"
        [personaType]="chatbotData()!.personaType"
        [promptSuggestions]="chatbotData()!.prompt_suggestions || []"
        [avatarUrl]="chatbotData()!.avatar_url"
        [persistSession]="chatbotData()!.persist_session"
        [citationTarget]="citationTarget()"
        [accentColor]="chatbotData()!.accent_color"
        [headerLogoUrl]="chatbotData()!.header_logo_url"
      />
      }
    </div>
  `,
  styleUrl: './chat.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class ChatComponent implements OnInit {
  private route = inject(ActivatedRoute);
  private router = inject(Router);
  private chatbotService = inject(ChatbotService);
  private authService = inject(AuthService);

  chatbotId = signal<string>('');
  chatbotName = signal<string>('');
  chatbotData = signal<ChatbotPublicInfo | null>(null);
  chatbotPassword = signal<string | null>(null);
  // '?embedded=true' makes citation links break out of the iframe to the host
  // page; otherwise they open in a new tab.
  citationTarget = signal<string>('_blank');

  accessDialogType = signal<AccessDialogType>('loading');
  errorMessage = signal<string | null>(null);
  passwordError = signal<string | null>(null);
  submittingPassword = signal<boolean>(false);

  // Tracks stored-password usage so we can surface a specific error if it fails.
  private usingStoredPassword = false;

  showAccessDialog = computed(() => {
    return !this.chatbotData();
  });

  ngOnInit(): void {
    if (this.route.snapshot.queryParamMap.get('embedded') === 'true') {
      this.citationTarget.set('_parent');
    }

    const id = this.route.snapshot.paramMap.get('id');
    if (id) {
      this.chatbotId.set(id);
      this.loadChatbot(id);
    } else {
      this.accessDialogType.set('error');
      this.errorMessage.set('chatAccess.error.noId');
    }
  }

  loadChatbot(id: string): void {
    this.accessDialogType.set('loading');
    this.errorMessage.set(null);
    this.passwordError.set(null);

    this.chatbotService.getChatbotInfo(id).subscribe({
      next: (info) => {
        if (!info.enabled) {
          this.accessDialogType.set('disabled');
          return;
        }

        if (info.status !== ChatbotStatus.READY) {
          this.accessDialogType.set(
            info.status === ChatbotStatus.PROCESSING ? 'processing' : 'error'
          );
          this.errorMessage.set(
            info.status === ChatbotStatus.ERROR
              ? 'chatAccess.error.chatbotError'
              : null
          );
          return;
        }

        this.handleAccessLevel(info);
      },
      error: (err) => {
        console.error('Error loading chatbot info:', err);
        this.accessDialogType.set('error');
        this.errorMessage.set('chatAccess.error.loadFailed');
      },
    });
  }

  private handleAccessLevel(info: ChatbotInfoResponse): void {
    switch (info.access_level) {
      case ChatbotAccessLevel.PUBLIC:
        this.accessChatbot(info.id, null);
        break;

      case ChatbotAccessLevel.PASSWORD:
        const storedPassword = sessionStorage.getItem(
          `chatbot_${info.id}_password`
        );
        if (storedPassword) {
          this.usingStoredPassword = true;
          this.accessChatbot(info.id, storedPassword);
        } else {
          this.accessDialogType.set('password');
        }
        break;

      case ChatbotAccessLevel.PRIVATE:
        if (!this.authService.isAuthenticated()) {
          this.accessDialogType.set('private');
          return;
        }
        this.accessChatbot(info.id, null);
        break;
    }
  }

  private accessChatbot(id: string, password: string | null): void {
    this.accessDialogType.set('loading');
    this.errorMessage.set(null);

    this.chatbotService.accessChatbot(id, password || undefined).subscribe({
      next: (chatbot) => {
        this.chatbotName.set(chatbot.name);

        if (chatbot.status !== ChatbotStatus.READY) {
          this.accessDialogType.set(
            chatbot.status === ChatbotStatus.PROCESSING ? 'processing' : 'error'
          );
          this.errorMessage.set(
            chatbot.status === ChatbotStatus.ERROR
              ? 'chatAccess.error.chatbotError'
              : null
          );
          return;
        }

        this.chatbotData.set(chatbot);

        if (password) {
          sessionStorage.setItem(`chatbot_${id}_password`, password);
          this.chatbotPassword.set(password);
        }

        this.passwordError.set(null);
        this.usingStoredPassword = false;
      },
      error: (err) => {
        console.error('Error accessing chatbot:', err);
        if (err.status === 401) {

          this.accessDialogType.set('private');
        } else if (err.status === 403) {
          const errorDetail = err.error?.detail || '';
          if (errorDetail.toLowerCase().includes('password')) {
            sessionStorage.removeItem(`chatbot_${this.chatbotId()}_password`);
            this.accessDialogType.set('password');
            if (this.usingStoredPassword) {
              this.passwordError.set('chatAccess.password.changed');
            } else if (this.submittingPassword()) {
              this.passwordError.set('chatAccess.password.incorrect');
            }
            this.submittingPassword.set(false);
            this.usingStoredPassword = false;
          } else {
            this.accessDialogType.set('error');
            this.errorMessage.set(errorDetail || 'chatAccess.error.accessDenied');
          }
        } else {
          this.accessDialogType.set('error');
          this.errorMessage.set('chatAccess.error.accessFailed');
        }
      },
    });
  }

  onSubmitPassword(password: string): void {
    this.submittingPassword.set(true);
    this.passwordError.set(null);
    this.accessChatbot(this.chatbotId(), password);
  }

  onCancel(): void {
    this.router.navigate(['/dashboard']);
  }

  onLogin(): void {
    this.authService.login();
  }
}
