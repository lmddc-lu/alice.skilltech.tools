import {
  ChangeDetectionStrategy,
  Component,
  computed,
  inject,
  signal,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { TranslatePipe } from '@ngx-translate/core';
import { ChatbotListComponent } from '../../shared/components/chatbot-list/chatbot-list.component';
import { RouterLink } from '@angular/router';
import { AuthService } from '../../../services/core/auth.service';
import { ChatbotService } from '../../../services/chatbot/chatbot.service';

@Component({
  selector: 'app-overview',
  imports: [TranslatePipe, ChatbotListComponent, RouterLink],
  templateUrl: './overview.component.html',
  styleUrl: './overview.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class OverviewComponent {
  private authService = inject(AuthService);
  private chatbotService = inject(ChatbotService);

  readonly user_name = computed(() => this.authService.userInfo()?.name ?? '');
  readonly loadingChatbots = signal(true);
  readonly chatbotsCount = signal(0);

  readonly showEmptyState = computed(
    () => !this.loadingChatbots() && this.chatbotsCount() === 0
  );

  constructor() {
    this.authService.getUserInfo().pipe(takeUntilDestroyed()).subscribe();

    this.chatbotService
      .getChatbots()
      .pipe(takeUntilDestroyed())
      .subscribe({
        next: (chatbots) => {
          this.chatbotsCount.set(chatbots.length);
          this.loadingChatbots.set(false);
        },
        error: () => {
          this.loadingChatbots.set(false);
        },
      });
  }
}
