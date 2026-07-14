import {
  ChangeDetectionStrategy,
  Component,
  OnInit,
  computed,
  effect,
  inject,
  signal,
} from '@angular/core';

import { FormsModule } from '@angular/forms';
import { ActivatedRoute, Router } from '@angular/router';
import { TranslatePipe, TranslateService } from '@ngx-translate/core';
import { ChatbotItem, ChatbotFile, ChatbotPersonaType, ChatbotStatus, JobFile, JobPhase, JobProgress, MoodleCourseInfo } from '../../../interfaces/chatbot-i';
import { ChatbotService } from '../../../services/chatbot/chatbot.service';
import { AuthService } from '../../../services/core/auth.service';
import { MoodleCoursesService } from '../../../services/courses/moodle-courses.service';
import { ChatInterfaceComponent } from '../../shared/chat-interface/chat-interface.component';
import { MoodleCoursesModalComponent } from '../../shared/components/moodle-courses-modal/moodle-courses-modal.component';
import { FileManagerModalComponent } from '../../shared/components/file-manager-modal/file-manager-modal.component';
import { QrCodeModalComponent } from '../../shared/components/qr-code-modal/qr-code-modal.component';
import { MoodleContentBrowserComponent } from '../../shared/components/moodle-content-browser/moodle-content-browser.component';
import { FileContentBrowserComponent } from '../../shared/components/file-content-browser/file-content-browser.component';
import { ChatbotSettingsComponent } from './chatbot-settings/chatbot-settings.component';
import { MlangPipe } from '../../../core/mlang.pipe';

interface PersonaCard {
  id: ChatbotPersonaType;
  titleKey: string;
  descriptionKey: string;
}

const AVATAR_ACCEPTED_MIME = ['image/png', 'image/jpeg', 'image/webp'];
const AVATAR_MAX_BYTES = 5 * 1024 * 1024;

const HEADER_LOGO_ACCEPTED_MIME = [
  'image/png',
  'image/jpeg',
  'image/webp',
  'image/svg+xml',
];
const HEADER_LOGO_MAX_BYTES = 5 * 1024 * 1024;
const DEFAULT_ACCENT_COLOR = '#ffbc15';

@Component({
  selector: 'app-edit-chatbot',
  imports: [
    FormsModule,
    TranslatePipe,
    ChatInterfaceComponent,
    MoodleCoursesModalComponent,
    FileManagerModalComponent,
    QrCodeModalComponent,
    MoodleContentBrowserComponent,
    FileContentBrowserComponent,
    ChatbotSettingsComponent,
    MlangPipe,
],
  templateUrl: './edit-chatbot.component.html',
  styleUrl: './edit-chatbot.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class EditChatbotComponent implements OnInit {
  private route = inject(ActivatedRoute);
  private router = inject(Router);
  private chatbotService = inject(ChatbotService);
  private authService = inject(AuthService);
  private moodleService = inject(MoodleCoursesService);
  private translate = inject(TranslateService);

  // Branding controls are reserved for instance admins.
  readonly isAdmin = this.authService.isAdmin;

  private static readonly POLL_INTERVAL_MS = 3000;

  chatbot = signal<ChatbotItem | null>(null);
  loading = signal(false);
  error = signal<string | null>(null);
  showQRModal = signal(false);

  constructor() {
    effect((onCleanup) => {
      if (!this.isProcessing()) return;
      const chatbotId = this.chatbot()?.id;
      if (!chatbotId) return;

      const id = setInterval(
        () => this.pollStatus(chatbotId),
        EditChatbotComponent.POLL_INTERVAL_MS
      );
      onCleanup(() => clearInterval(id));
    });
  }

  private pollStatus(chatbotId: string): void {
    this.chatbotService.getChatbotById(chatbotId).subscribe({
      next: (chatbot) => {
        const prevStatus = this.chatbot()?.status;
        const nextStatus = chatbot.status;

        this.chatbot.set(chatbot);

        if (
          prevStatus === ChatbotStatus.PROCESSING &&
          (nextStatus === ChatbotStatus.READY ||
            nextStatus === ChatbotStatus.ERROR)
        ) {
          this.jobProgress.set(null);
          this.jobPhase.set(null);
          this.jobFiles.set([]);
          this.filesExpanded.set(false);
          this.loadFiles(chatbotId);
        }
      },
      error: (err) => console.error('Error polling chatbot status:', err),
    });

    this.chatbotService.getJobStatus(chatbotId).subscribe({
      next: (jobStatus) => {
        if (jobStatus.progress) this.jobProgress.set(jobStatus.progress);
        this.jobPhase.set(jobStatus.phase ?? null);
        this.jobFiles.set(jobStatus.files ?? []);
      },
      error: (err) => console.error('Error polling job status:', err),
    });
  }

  isEditingName = signal(false);
  isEditingDescription = signal(false);
  isEditingPersona = signal(false);

  isEditingSuggestions = signal(false);

  editNameValue = signal('');
  editDescriptionValue = signal('');
  editPersonaValue = signal('');
  editSuggestionsValue = signal<string[]>([]);
  selectedPersonaCard = signal<ChatbotPersonaType>('teacher');
  private originalPersona = signal<string>('');
  private originalPersonaCardId = signal<ChatbotPersonaType>('teacher');

  isPersonaModified = computed(() => {
    const currentCard = this.selectedPersonaCard();
    const currentValue = this.editPersonaValue();
    const originalCard = this.originalPersonaCardId();
    const originalValue = this.originalPersona();

    return currentCard !== originalCard || currentValue !== originalValue;
  });

  isSynchronising = signal(false);
  isCancelling = signal(false);
  isDeleting = signal(false);
  // Recoverable sync/delete errors. The page-level `error` signal is fatal
  // (hides the UI), so inline these instead.
  actionError = signal<string | null>(null);

  showPreview = signal(false);
  isProcessing = computed(() => this.chatbot()?.status === ChatbotStatus.PROCESSING);
  canPreview = computed(() => this.chatbot()?.status === ChatbotStatus.READY);
  jobProgress = signal<JobProgress | null>(null);
  jobPhase = signal<JobPhase | null>(null);
  jobFiles = signal<JobFile[]>([]);
  filesExpanded = signal(false);

  hasJobFiles = computed(() => this.jobFiles().length > 0);
  isWaitingMetadata = computed(() => this.jobPhase() === 'waiting_metadata');

  // Derived from the enriched /files endpoint (server joins the latest
  // JobFile row), so this survives API restarts without re-stitching
  // /job-status on the client.
  failedFiles = computed(() =>
    this.files().filter((f) => f.ingestion_state === 'failed')
  );
  hasFailedFiles = computed(() => this.failedFiles().length > 0);

  // Translation key per stable sync-error code stored in last_sync_error.
  // Unknown or legacy (pre-code) values fall back to the generic key.
  private readonly syncErrorKeys: Record<string, string> = {
    stalled: 'editChatbot.syncError.stalled',
    cancelled: 'editChatbot.syncError.cancelled',
    failed: 'editChatbot.syncError.failed',
    partial_failure: 'editChatbot.syncError.partialFailure',
  };

  // Populated only on a failed sync; surfaced inline so the owner can act on
  // the cause without needing an admin to open the job detail. Maps the stored
  // code to a translation key so the message is localized and user-friendly.
  syncErrorKey = computed(() => {
    const cb = this.chatbot();
    if (cb?.status !== ChatbotStatus.ERROR || !cb.last_sync_error) {
      return null;
    }
    return (
      this.syncErrorKeys[cb.last_sync_error] ?? 'editChatbot.syncError.generic'
    );
  });

  toggleFilesExpanded(): void {
    this.filesExpanded.update((v) => !v);
  }

  showFileManager = signal(false);
  files = signal<ChatbotFile[]>([]);
  linkedCourses = signal<MoodleCourseInfo[]>([]);

  showMoodleContentBrowser = signal(false);
  showFileContentBrowser = signal(false);
  isModalOpen = signal(false);
  recentlyUpdated = signal(false);
  coursesCount = signal(0);

  useCustomAvatar = signal(false);
  avatarPreviewUrl = signal<string | null>(null);
  isUploadingAvatar = signal(false);
  avatarError = signal<string | null>(null);

  hasCustomAvatarImage = computed(() => {
    if (this.avatarPreviewUrl()) return true;
    return this.useCustomAvatar() && !!this.chatbot()?.avatar_url;
  });

  customAvatarUrl = computed(
    () => this.avatarPreviewUrl() ?? this.chatbot()?.avatar_url ?? null
  );

  // Branding editing state (admin only). The accent colour defaults to the
  // built-in look so the picker always shows a concrete value.
  accentColorValue = signal(DEFAULT_ACCENT_COLOR);
  headerLogoPreviewUrl = signal<string | null>(null);
  isUploadingHeaderLogo = signal(false);
  brandingError = signal<string | null>(null);

  customHeaderLogoUrl = computed(
    () => this.headerLogoPreviewUrl() ?? this.chatbot()?.header_logo_url ?? null
  );

  personaCards = signal<PersonaCard[]>([
    {
      id: 'teacher',
      titleKey: 'editChatbot.personaTeacher',
      descriptionKey: 'editChatbot.personaTeacherDescription',
    },
    {
      id: 'studycompanion',
      titleKey: 'editChatbot.personaStudyCompanion',
      descriptionKey: 'editChatbot.personaStudyCompanionDescription',
    },
    {
      id: 'custom',
      titleKey: 'editChatbot.personaCustom',
      descriptionKey: 'editChatbot.personaCustomDescription',
    },
  ]);

  hasMoodleCourses = computed(() => {
    const types = this.chatbot()?.datasource_types ?? [];
    return types.includes('MOODLE');
  });

  hasFilesDatasource = computed(() => {
    const types = this.chatbot()?.datasource_types ?? [];
    return types.includes('FILE');
  });

  linkedCoursesCount = computed(() => {
    return this.linkedCourses().length;
  });

  statusConfig = computed(() => {
    const status = this.chatbot()?.status;
    switch (status) {
      case ChatbotStatus.READY:
        return { label: 'editChatbot.statusReady', class: 'status-ready', icon: 'check-circle2' };
      case ChatbotStatus.PROCESSING:
        return {
          label: 'editChatbot.statusProcessing',
          class: 'status-syncing',
          icon: 'refresh',
        };
      case ChatbotStatus.ERROR:
      default:
        return { label: 'editChatbot.statusError', class: 'status-error', icon: 'x-circle' };
    }
  });

  handleModalClose(): void {
    this.isModalOpen.set(false);
  }

  handleMoodleContentBrowserClose(): void {
    this.showMoodleContentBrowser.set(false);
  }

  handleFileContentBrowserClose(): void {
    this.showFileContentBrowser.set(false);
  }

  handleFileManagerClose(): void {
    this.showFileManager.set(false);
  }

  handleFilesSaved(): void {
    this.showFileManager.set(false);
    const chatbot = this.chatbot();
    if (chatbot) {
      this.loadChatbot(chatbot.id);
    }
  }


  handleCoursesSaved(): void {
    this.isModalOpen.set(false);
    this.recentlyUpdated.set(true);

    const chatbot = this.chatbot();
    if (chatbot) {
      this.loadChatbot(chatbot.id);
    }

    setTimeout(() => {
      this.recentlyUpdated.set(false);
    }, 5000);
  }

  handleChatbotChange(updatedChatbot: ChatbotItem): void {
    this.chatbot.set(updatedChatbot);
  }

  ngOnInit(): void {
    const id = this.route.snapshot.paramMap.get('id');
    if (id) {
      this.loadChatbot(id);
    } else {
      this.error.set('No chatbot ID provided');
    }
  }

  private loadChatbot(id: string): void {
    this.loading.set(true);
    this.error.set(null);

    this.chatbotService.getChatbotById(id).subscribe({
      next: (chatbot) => {
        this.chatbot.set(chatbot);
        this.initializeEditValues(chatbot);
        this.loading.set(false);
        if (chatbot.status === ChatbotStatus.PROCESSING) {
          // Polling fires every 3s via the constructor effect; kick one
          // immediate fetch so the progress bar paints on initial load.
          this.fetchJobStatusOnce(id);
        }
        this.loadFiles(id);
        this.loadMoodleCourses(id, chatbot.datasource_types);
      },
      error: (err) => {
        console.error('Error loading chatbot:', err);
        this.error.set('Failed to load chatbot');
        this.loading.set(false);
      },
    });
  }

  private loadFiles(chatbotId: string): void {
    this.chatbotService.listFiles(chatbotId).subscribe({
      next: (res) => this.files.set(res.files),
      error: (err) => console.error('Error loading files:', err),
    });
  }

  private fetchJobStatusOnce(chatbotId: string): void {
    this.chatbotService.getJobStatus(chatbotId).subscribe({
      next: (jobStatus) => {
        if (jobStatus.progress) {
          this.jobProgress.set(jobStatus.progress);
        }
        this.jobPhase.set(jobStatus.phase ?? null);
        this.jobFiles.set(jobStatus.files ?? []);
      },
      error: (err) => console.error('Error fetching job status:', err),
    });
  }

  private loadMoodleCourses(chatbotId: string, datasourceTypes: string[]): void {
    if (!datasourceTypes.includes('MOODLE')) return;
    this.moodleService.getMoodleCourses(chatbotId).subscribe({
      next: (res) => this.linkedCourses.set(res.linked_courses),
      error: (err) => console.error('Error loading moodle courses:', err),
    });
  }

  private initializeEditValues(chatbot: ChatbotItem): void {
    this.editNameValue.set(chatbot.name);
    this.editDescriptionValue.set(chatbot.description || '');
    this.editPersonaValue.set(chatbot.persona || '');
    this.editSuggestionsValue.set(chatbot.prompt_suggestions ?? []);

    this.originalPersona.set(chatbot.persona || '');

    const personaType = chatbot.personaType || 'teacher';
    this.selectedPersonaCard.set(personaType);
    this.originalPersonaCardId.set(personaType);

    this.useCustomAvatar.set(!!chatbot.avatar_storage_path);
    this.avatarPreviewUrl.set(null);
    this.avatarError.set(null);

    this.accentColorValue.set(chatbot.accent_color ?? DEFAULT_ACCENT_COLOR);
    this.headerLogoPreviewUrl.set(null);
    this.brandingError.set(null);
  }

  startEditingName(): void {
    this.isEditingName.set(true);
    this.editNameValue.set(this.chatbot()?.name || '');
  }

  saveName(): void {
    const newName = this.editNameValue().trim();
    const chatbot = this.chatbot();

    if (newName && chatbot) {
      this.chatbotService
        .updateChatbot(chatbot.id, { name: newName })
        .subscribe({
          next: (updatedChatbot) => {
            this.chatbot.set(updatedChatbot);
            this.isEditingName.set(false);
          },
          error: (err) => {
            console.error('Error updating name:', err);
          },
        });
    }
  }

  cancelEditName(): void {
    this.editNameValue.set(this.chatbot()?.name || '');
    this.isEditingName.set(false);
  }

  startEditingDescription(): void {
    this.isEditingDescription.set(true);
    this.editDescriptionValue.set(this.chatbot()?.description || '');
  }

  saveDescription(): void {
    const newDescription = this.editDescriptionValue().trim();
    const chatbot = this.chatbot();

    if (chatbot) {
      this.chatbotService
        .updateChatbot(chatbot.id, { description: newDescription })
        .subscribe({
          next: (updatedChatbot) => {
            this.chatbot.set(updatedChatbot);
            this.isEditingDescription.set(false);
          },
          error: (err) => {
            console.error('Error updating description:', err);
          },
        });
    }
  }

  cancelEditDescription(): void {
    this.editDescriptionValue.set(this.chatbot()?.description || '');
    this.isEditingDescription.set(false);
  }

  selectPersonaCard(cardId: ChatbotPersonaType): void {
    this.selectedPersonaCard.set(cardId);
  }

  startEditingPersona(): void {
    this.isEditingPersona.set(true);
  }

  savePersona(): void {
    const newPersona = this.editPersonaValue().trim();
    const newPersonaType = this.selectedPersonaCard();
    const chatbot = this.chatbot();

    if (chatbot) {
      this.chatbotService
        .updateChatbot(chatbot.id, { persona: newPersona, personaType: newPersonaType })
        .subscribe({
          next: (updatedChatbot) => {
            this.chatbot.set(updatedChatbot);
            this.originalPersona.set(newPersona);
            this.originalPersonaCardId.set(newPersonaType);
            this.isEditingPersona.set(false);
          },
          error: (err) => {
            console.error('Error updating persona:', err);
          },
        });
    }
  }

  cancelEditPersona(): void {
    this.editPersonaValue.set(this.originalPersona());
    this.selectedPersonaCard.set(this.originalPersonaCardId());
    this.isEditingPersona.set(false);
  }

  startEditingSuggestions(): void {
    this.isEditingSuggestions.set(true);
    this.editSuggestionsValue.set([...(this.chatbot()?.prompt_suggestions ?? [])]);
  }

  startEditingSuggestionsWithNew(): void {
    this.isEditingSuggestions.set(true);
    this.editSuggestionsValue.set([...(this.chatbot()?.prompt_suggestions ?? []), '']);
  }

  addSuggestion(): void {
    const current = this.editSuggestionsValue();
    if (current.length < 4) {
      this.editSuggestionsValue.set([...current, '']);
    }
  }

  removeSuggestion(index: number): void {
    const current = this.editSuggestionsValue();
    this.editSuggestionsValue.set(current.filter((_, i) => i !== index));
  }

  updateSuggestion(index: number, value: string): void {
    const current = [...this.editSuggestionsValue()];
    current[index] = value;
    this.editSuggestionsValue.set(current);
  }

  saveSuggestions(): void {
    const chatbot = this.chatbot();
    if (!chatbot) return;

    const suggestions = this.editSuggestionsValue()
      .map((s) => s.trim())
      .filter((s) => s.length > 0);

    this.chatbotService
      .updateChatbot(chatbot.id, { prompt_suggestions: suggestions })
      .subscribe({
        next: (updatedChatbot) => {
          this.chatbot.set(updatedChatbot);
          this.editSuggestionsValue.set(updatedChatbot.prompt_suggestions ?? []);
          this.isEditingSuggestions.set(false);
        },
        error: (err) => {
          console.error('Error updating prompt suggestions:', err);
        },
      });
  }

  cancelEditSuggestions(): void {
    this.editSuggestionsValue.set([...(this.chatbot()?.prompt_suggestions ?? [])]);
    this.isEditingSuggestions.set(false);
  }

  toggleCiteSources(citeSources: boolean): void {
    const chatbot = this.chatbot();
    if (!chatbot) return;

    this.chatbotService
      .updateChatbot(chatbot.id, { cite_sources: citeSources })
      .subscribe({
        next: (updatedChatbot) => {
          this.chatbot.set(updatedChatbot);
        },
        error: (err) => {
          console.error('Error updating cite_sources:', err);
        },
      });
  }

  toggleForceOcr(forceOcr: boolean): void {
    const chatbot = this.chatbot();
    if (!chatbot) return;

    this.chatbotService
      .updateChatbot(chatbot.id, { force_ocr: forceOcr })
      .subscribe({
        next: (updatedChatbot) => {
          this.chatbot.set(updatedChatbot);
        },
        error: (err) => {
          console.error('Error updating force_ocr:', err);
        },
      });
  }

  toggleCustomAvatar(enabled: boolean): void {
    this.avatarError.set(null);
    this.useCustomAvatar.set(enabled);

    if (!enabled) {
      this.avatarPreviewUrl.set(null);
      const chatbot = this.chatbot();
      // Only call the server when an avatar is actually persisted; toggling
      // without ever uploading stays client-side.
      if (chatbot?.avatar_storage_path) {
        this.chatbotService.deleteAvatar(chatbot.id).subscribe({
          next: (updated) => this.chatbot.set(updated),
          error: (err) => {
            console.error('Error removing avatar:', err);
            this.useCustomAvatar.set(true);
            this.avatarError.set('editChatbot.avatarRemoveFailed');
          },
        });
      }
    }
  }

  onAvatarFileSelected(event: Event): void {
    const input = event.target as HTMLInputElement;
    const file = input.files?.[0];
    input.value = '';
    if (!file) return;

    this.avatarError.set(null);

    if (!AVATAR_ACCEPTED_MIME.includes(file.type)) {
      this.avatarError.set('editChatbot.avatarInvalidType');
      return;
    }
    if (file.size > AVATAR_MAX_BYTES) {
      this.avatarError.set('editChatbot.avatarTooLarge');
      return;
    }

    const chatbot = this.chatbot();
    if (!chatbot) return;

    const reader = new FileReader();
    reader.onload = () => this.avatarPreviewUrl.set(reader.result as string);
    reader.readAsDataURL(file);

    this.isUploadingAvatar.set(true);
    this.chatbotService.uploadAvatar(chatbot.id, file).subscribe({
      next: (updated) => {
        this.chatbot.set(updated);
        this.useCustomAvatar.set(true);
        this.avatarPreviewUrl.set(null);
        this.isUploadingAvatar.set(false);
      },
      error: (err) => {
        console.error('Error uploading avatar:', err);
        this.avatarPreviewUrl.set(null);
        this.avatarError.set('editChatbot.avatarUploadFailed');
        this.isUploadingAvatar.set(false);
      },
    });
  }

  onAccentColorChange(color: string): void {
    this.accentColorValue.set(color);
    this.saveBrandingColors();
  }

  private saveBrandingColors(): void {
    const chatbot = this.chatbot();
    if (!chatbot) return;

    this.brandingError.set(null);
    this.chatbotService
      .updateChatbot(chatbot.id, {
        accent_color: this.accentColorValue(),
      })
      .subscribe({
        next: (updated) => this.chatbot.set(updated),
        error: (err) => {
          console.error('Error saving branding colors:', err);
          this.brandingError.set('editChatbot.brandingSaveFailed');
        },
      });
  }

  onHeaderLogoFileSelected(event: Event): void {
    const input = event.target as HTMLInputElement;
    const file = input.files?.[0];
    input.value = '';
    if (!file) return;

    this.brandingError.set(null);

    if (!HEADER_LOGO_ACCEPTED_MIME.includes(file.type)) {
      this.brandingError.set('editChatbot.headerLogoInvalidType');
      return;
    }
    if (file.size > HEADER_LOGO_MAX_BYTES) {
      this.brandingError.set('editChatbot.headerLogoTooLarge');
      return;
    }

    const chatbot = this.chatbot();
    if (!chatbot) return;

    const reader = new FileReader();
    reader.onload = () => this.headerLogoPreviewUrl.set(reader.result as string);
    reader.readAsDataURL(file);

    this.isUploadingHeaderLogo.set(true);
    this.chatbotService.uploadHeaderLogo(chatbot.id, file).subscribe({
      next: (updated) => {
        this.chatbot.set(updated);
        this.headerLogoPreviewUrl.set(null);
        this.isUploadingHeaderLogo.set(false);
      },
      error: (err) => {
        console.error('Error uploading header logo:', err);
        this.headerLogoPreviewUrl.set(null);
        this.brandingError.set('editChatbot.headerLogoUploadFailed');
        this.isUploadingHeaderLogo.set(false);
      },
    });
  }

  removeHeaderLogo(): void {
    const chatbot = this.chatbot();
    if (!chatbot?.header_logo_storage_path) {
      this.headerLogoPreviewUrl.set(null);
      return;
    }

    this.brandingError.set(null);
    this.chatbotService.deleteHeaderLogo(chatbot.id).subscribe({
      next: (updated) => {
        this.chatbot.set(updated);
        this.headerLogoPreviewUrl.set(null);
      },
      error: (err) => {
        console.error('Error removing header logo:', err);
        this.brandingError.set('editChatbot.headerLogoRemoveFailed');
      },
    });
  }

  manageFiles(): void {
    this.showFileManager.set(true);
  }

  synchronizeChatbot(): void {
    const chatbot = this.chatbot();
    if (!chatbot || this.isSynchronising()) return;

    this.isSynchronising.set(true);
    this.showPreview.set(false);
    this.actionError.set(null);

    this.chatbotService.synchronizeChatbot(chatbot.id).subscribe({
      next: () => {
        this.chatbot.update((c) =>
          c ? { ...c, status: ChatbotStatus.PROCESSING } : null
        );
        this.isSynchronising.set(false);
      },
      error: (err) => {
        console.error('Error synchronizing chatbot:', err);
        this.actionError.set('editChatbot.syncFailed');
        this.isSynchronising.set(false);
      },
    });
  }

  cancelIndexing(): void {
    const chatbot = this.chatbot();
    if (!chatbot || this.isCancelling()) return;

    this.isCancelling.set(true);

    this.chatbotService.cancelIndexing(chatbot.id).subscribe({
      next: () => {
        this.jobProgress.set(null);
        this.jobPhase.set(null);
        this.jobFiles.set([]);
        this.chatbot.update((c) =>
          c ? { ...c, status: ChatbotStatus.ERROR } : null
        );
        this.isCancelling.set(false);
      },
      error: (err) => {
        console.error('Error cancelling indexing:', err);
        this.isCancelling.set(false);
      },
    });
  }

  previewChatbot(): void {
    this.showPreview.update((show) => !show);
  }

  deleteChatbot(): void {
    const chatbot = this.chatbot();
    if (!chatbot || this.isDeleting()) return;

    const confirmDelete = confirm(
      this.translate.instant('editChatbot.confirmDeleteMessage', { name: chatbot.name })
    );
    if (!confirmDelete) return;

    this.isDeleting.set(true);
    this.actionError.set(null);

    this.chatbotService.deleteChatbot(chatbot.id).subscribe({
      next: () => {
        this.isDeleting.set(false);
        this.router.navigate(['/dashboard']);
      },
      error: (err) => {
        console.error('Error deleting chatbot:', err);
        this.actionError.set('editChatbot.deleteFailed');
        this.isDeleting.set(false);
      },
    });
  }

  goBack(): void {
    this.router.navigate(['/dashboard']);
  }
}
