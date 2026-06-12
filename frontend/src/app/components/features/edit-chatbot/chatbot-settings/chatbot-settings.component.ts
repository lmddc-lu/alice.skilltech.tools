import {
  Component,
  ChangeDetectionStrategy,
  computed,
  effect,
  signal,
  inject,
  input,
  output,
} from '@angular/core';
import { FormsModule } from '@angular/forms';
import { TranslatePipe, TranslateService } from '@ngx-translate/core';
import {
  ChatbotItem,
  ReindexFrequency,
} from '../../../../interfaces/chatbot-i';
import { ChatbotService } from '../../../../services/chatbot/chatbot.service';

@Component({
  selector: 'app-chatbot-settings',
  imports: [FormsModule, TranslatePipe],
  templateUrl: './chatbot-settings.component.html',
  styleUrl: './chatbot-settings.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class ChatbotSettingsComponent {
  private chatbotService = inject(ChatbotService);
  private translate = inject(TranslateService);

  chatbot = input.required<ChatbotItem>();
  chatbotChange = output<ChatbotItem>();
  showQRModal = output<void>();

  isEditingPassword = signal(false);
  editPasswordValue = signal('');
  showPasswordInput = signal(false);

  showToken = signal(false);
  showApiToken = signal(false);

  isRotatingApiToken = signal(false);

  maskedToken = computed(() => {
    const token = this.chatbot().chatbot_token;
    if (!token || this.showToken()) return token || '';
    if (token.length <= 24) return '•'.repeat(token.length);
    return (
      token.slice(0, 12) + '•'.repeat(token.length - 24) + token.slice(-12)
    );
  });

  maskedApiToken = computed(() => {
    const token = this.chatbot().token;
    if (!token || this.showApiToken()) return token || '';
    if (token.length <= 8) return '•'.repeat(token.length);
    return token.slice(0, 4) + '•'.repeat(token.length - 8) + token.slice(-4);
  });

  apiEndpointUrl = computed(() => {
    const chatbotUrl = this.chatbot().chatbot_url;
    if (!chatbotUrl) return '';
    try {
      const url = new URL(chatbotUrl);
      return `${url.origin}/api/v1/chat/completions`;
    } catch {
      return '';
    }
  });

  updateAccessLevel(accessLevel: 'public' | 'private' | 'password'): void {
    const chatbot = this.chatbot();

    if (accessLevel === 'password') {
      this.showPasswordInput.set(true);
      this.isEditingPassword.set(true);
      this.editPasswordValue.set('');
      this.chatbotChange.emit({ ...chatbot, access_level: accessLevel });
      return;
    }

    this.showPasswordInput.set(false);
    this.isEditingPassword.set(false);

    this.chatbotService
      .updateChatbot(chatbot.id, {
        access_level: accessLevel,
        password: null,
      })
      .subscribe({
        next: (updatedChatbot) => {
          this.chatbotChange.emit({
            ...updatedChatbot,
            access_level: updatedChatbot.access_level,
            password: null,
          });
        },
        error: (err) => {
          console.error('Error updating access level:', err);
          alert('Failed to update access level. Please try again.');
        },
      });
  }

  savePassword(): void {
    const chatbot = this.chatbot();
    const password = this.editPasswordValue().trim();

    if (!password) {
      alert('Please enter a password');
      return;
    }

    if (password.length < 6) {
      alert('Password must be at least 6 characters long');
      return;
    }

    this.chatbotService
      .updateChatbot(chatbot.id, {
        access_level: 'password',
        password: password,
      })
      .subscribe({
        next: (updatedChatbot) => {
          this.chatbotChange.emit(updatedChatbot);
          this.isEditingPassword.set(false);
          this.showPasswordInput.set(true);
        },
        error: (err) => {
          console.error('Error setting password:', err);
          alert('Failed to set password. Please try again.');
        },
      });
  }

  cancelPasswordEdit(): void {
    const chatbot = this.chatbot();

    if (!chatbot.password) {
      this.chatbotChange.emit({ ...chatbot, access_level: 'public' });
    }

    this.isEditingPassword.set(false);
    this.showPasswordInput.set(false);
    this.editPasswordValue.set('');
  }

  changePassword(): void {
    this.isEditingPassword.set(true);
    this.editPasswordValue.set('');
  }

  copyUrl(): void {
    const url = this.chatbot().chatbot_url;
    if (url) {
      navigator.clipboard.writeText(url).catch((err) => {
        console.error('Failed to copy URL:', err);
      });
    }
  }

  toggleTokenVisibility(): void {
    this.showToken.update((show) => !show);
  }

  copyToken(): void {
    const token = this.chatbot().chatbot_token;
    if (token) {
      navigator.clipboard.writeText(token).catch((err) => {
        console.error('Failed to copy token:', err);
      });
    }
  }

  toggleApiTokenVisibility(): void {
    this.showApiToken.update((show) => !show);
  }

  copyApiToken(): void {
    const token = this.chatbot().token;
    if (token) {
      navigator.clipboard.writeText(token).catch((err) => {
        console.error('Failed to copy API token:', err);
      });
    }
  }

  rotateApiToken(): void {
    if (this.isRotatingApiToken()) return;

    const chatbot = this.chatbot();
    const confirmed = window.confirm(
      this.translate.instant('editChatbot.rotateApiKeyConfirm')
    );
    if (!confirmed) return;

    this.isRotatingApiToken.set(true);
    this.chatbotService.rotateChatbotToken(chatbot.id).subscribe({
      next: (updatedChatbot) => {
        this.chatbotChange.emit({ ...chatbot, token: updatedChatbot.token });
        this.showApiToken.set(true);
        this.isRotatingApiToken.set(false);
      },
      error: (err) => {
        console.error('Error rotating API token:', err);
        alert(this.translate.instant('editChatbot.rotateApiKeyFailed'));
        this.isRotatingApiToken.set(false);
      },
    });
  }

  copyApiEndpoint(): void {
    const url = this.apiEndpointUrl();
    if (url) {
      navigator.clipboard.writeText(url).catch((err) => {
        console.error('Failed to copy API endpoint URL:', err);
      });
    }
  }

  toggleChatbotStatus(): void {
    const chatbot = this.chatbot();
    const newStatus = !chatbot.enabled;

    this.chatbotService
      .updateChatbot(chatbot.id, { enabled: newStatus })
      .subscribe({
        next: (updatedChatbot) => {
          this.chatbotChange.emit({ ...chatbot, enabled: updatedChatbot.enabled });
        },
        error: (err) => {
          console.error('Error toggling chatbot status:', err);
        },
      });
  }

  toggleApiEnabled(): void {
    const chatbot = this.chatbot();
    const newValue = !chatbot.api_enabled;

    this.chatbotService
      .updateChatbot(chatbot.id, { api_enabled: newValue })
      .subscribe({
        next: (updatedChatbot) => {
          this.chatbotChange.emit({ ...chatbot, api_enabled: updatedChatbot.api_enabled });
        },
        error: (err) => {
          console.error('Error toggling API access:', err);
        },
      });
  }

  togglePersistSession(): void {
    const chatbot = this.chatbot();
    const newValue = !chatbot.persist_session;

    this.chatbotService
      .updateChatbot(chatbot.id, { persist_session: newValue })
      .subscribe({
        next: (updatedChatbot) => {
          this.chatbotChange.emit({
            ...chatbot,
            persist_session: updatedChatbot.persist_session,
          });
        },
        error: (err) => {
          console.error('Error toggling session persistence:', err);
        },
      });
  }

  togglePiiFilter(): void {
    const chatbot = this.chatbot();
    const newValue = !chatbot.pii_filter_enabled;

    this.chatbotService
      .updateChatbot(chatbot.id, { pii_filter_enabled: newValue })
      .subscribe({
        next: (updatedChatbot) => {
          this.chatbotChange.emit({
            ...chatbot,
            pii_filter_enabled: updatedChatbot.pii_filter_enabled,
          });
        },
        error: (err) => {
          console.error('Error toggling PII filter:', err);
        },
      });
  }

  // Backend rejects reindex scheduling for file-only KBs since file edits
  // already trigger a reingest.
  hasMoodleDatasource = computed(() =>
    this.chatbot().datasource_types.includes('MOODLE')
  );

  scheduleEnabled = signal(false);
  scheduleFrequency = signal<ReindexFrequency>('weekly');
  scheduleDayOfWeek = signal(6);
  scheduleDayOfMonth = signal(1);
  scheduleHour = signal(6);
  scheduleMinute = signal(0);
  isSavingSchedule = signal(false);
  scheduleError = signal<string | null>(null);

  // Quarter-hour preset for the minute <select>.
  scheduleMinutePreset = computed(() => {
    const m = this.scheduleMinute();
    if (m < 15) return 0;
    if (m < 30) return 15;
    if (m < 45) return 30;
    return 45;
  });

  daysOfWeek: ReadonlyArray<{ value: number; labelKey: string }> = [
    { value: 0, labelKey: 'editChatbot.dayMonday' },
    { value: 1, labelKey: 'editChatbot.dayTuesday' },
    { value: 2, labelKey: 'editChatbot.dayWednesday' },
    { value: 3, labelKey: 'editChatbot.dayThursday' },
    { value: 4, labelKey: 'editChatbot.dayFriday' },
    { value: 5, labelKey: 'editChatbot.daySaturday' },
    { value: 6, labelKey: 'editChatbot.daySunday' },
  ];

  daysOfMonth: ReadonlyArray<number> = Array.from(
    { length: 28 },
    (_, i) => i + 1
  );

  hours: ReadonlyArray<number> = Array.from({ length: 24 }, (_, i) => i);

  constructor() {
    effect(() => {
      const c = this.chatbot();
      this.scheduleEnabled.set(c.reindex_schedule_enabled);
      this.scheduleFrequency.set(
        c.reindex_schedule_frequency ?? 'weekly'
      );
      this.scheduleDayOfWeek.set(c.reindex_schedule_day_of_week ?? 6);
      this.scheduleDayOfMonth.set(c.reindex_schedule_day_of_month ?? 1);
      this.scheduleHour.set(c.reindex_schedule_hour ?? 6);
      this.scheduleMinute.set(c.reindex_schedule_minute ?? 0);
      this.scheduleError.set(null);
    });
  }

  onScheduleMinutePresetChange(value: number): void {
    this.scheduleMinute.set(value);
  }

  saveSchedule(): void {
    const chatbot = this.chatbot();
    if (this.isSavingSchedule()) return;

    const enabled = this.scheduleEnabled();
    const frequency = this.scheduleFrequency();

    const payload = {
      enabled,
      frequency: enabled ? frequency : null,
      day_of_week:
        enabled && frequency === 'weekly' ? this.scheduleDayOfWeek() : null,
      day_of_month:
        enabled && frequency === 'monthly' ? this.scheduleDayOfMonth() : null,
      hour: enabled ? this.scheduleHour() : null,
      minute: this.scheduleMinute(),
    };

    this.isSavingSchedule.set(true);
    this.scheduleError.set(null);

    this.chatbotService.setReindexSchedule(chatbot.id, payload).subscribe({
      next: (schedule) => {
        this.chatbotChange.emit({
          ...chatbot,
          reindex_schedule_enabled: schedule.enabled,
          reindex_schedule_frequency: schedule.frequency,
          reindex_schedule_day_of_week: schedule.day_of_week,
          reindex_schedule_day_of_month: schedule.day_of_month,
          reindex_schedule_hour: schedule.hour,
          reindex_schedule_minute: schedule.minute,
        });
        this.isSavingSchedule.set(false);
      },
      error: (err) => {
        console.error('Error saving reindex schedule:', err);
        this.scheduleError.set(
          err?.error?.detail ?? 'editChatbot.scheduleSaveFailed'
        );
        this.isSavingSchedule.set(false);
      },
    });
  }
}
