import {
  Component,
  signal,
  computed,
  inject,
  ChangeDetectionStrategy,
} from '@angular/core';

import { Router } from '@angular/router';
import { HttpClient } from '@angular/common/http';
import { TranslatePipe, TranslateService } from '@ngx-translate/core';
import { BasicInfoStepComponent } from '../steps/basic-info-step/basic-info-step.component';
import { ChatbotConfigStepComponent } from '../steps/chatbot-config-step/chatbot-config-step.component';
import { ContentSelectionStepComponent } from '../steps/content-selection-step/content-selection-step.component';
import { CourseSelectionStepComponent } from '../steps/course-selection-step/course-selection-step.component';
import { ReviewConfirmStepComponent } from '../steps/review-confirm-step/review-confirm-step.component';
import { SourceTypeStepComponent } from '../steps/source-type-step/source-type-step.component';
import { FileUploadStepComponent } from '../steps/file-upload-step/file-upload-step.component';
import { ChatbotService } from '../../../services/chatbot/chatbot.service';
import { firstValueFrom } from 'rxjs';

export interface WizardData {
  sourceType: 'moodle' | 'files';

  name: string;
  description: string;

  moodleUrl: string;
  moodleToken: string;
  connectionVerified: boolean;
  courses: MoodleCourse[];
  selectedCourses: string[];

  uploadedFiles: UploadedFileInfo[];
  textEntries: WizardTextEntry[];
  forceOcr: boolean;

  chatbotType: 'teacher' | 'studycompanion' | 'custom';
  customPersona: string;
  promptSuggestions: string[];
  citeSources: boolean;

  contentTypes: {
    pdf: boolean;
    presentations: boolean;
    web: boolean;
    forums: boolean;
    scorm: boolean;
    glossaries: boolean;
    books: boolean;
    wiki: boolean;
  };

  selectedContent: SelectedContent[];
}

export interface UploadedFileInfo {
  id: string;
  file: File;
  name: string;
  size: number;
  type: string;
  uploadProgress: number;
  status: 'pending' | 'uploading' | 'completed' | 'error';
  error?: string;
}

export interface WizardTextEntry {
  id: string;
  title: string;
  content: string;
}

export interface MoodleCourse {
  id: number;
  fullname: string;
  name: string;
  shortname: string;
  category: string;
  description?: string;
  course_url?: string;
}

export interface SelectedContent {
  courseId: string;
  courseName: string;
  items: ContentItem[];
}

export interface ContentItem {
  id: string;
  name: string;
  type: string;
  size?: number;
  selected: boolean;
}

interface WizardStep {
  id: string;
  number: number;
  label: string;
  description: string;
  icon: string;
}

@Component({
  selector: 'app-new-chatbot',
  templateUrl: './new-chatbot.component.html',
  styleUrl: './new-chatbot.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    BasicInfoStepComponent,
    CourseSelectionStepComponent,
    ChatbotConfigStepComponent,
    ContentSelectionStepComponent,
    ReviewConfirmStepComponent,
    SourceTypeStepComponent,
    FileUploadStepComponent,
    TranslatePipe
],
})
export class NewChatbotComponent {
  private router = inject(Router);
  private http = inject(HttpClient);
  private chatbotService = inject(ChatbotService);
  private translate = inject(TranslateService);

  currentStep = signal(1);
  isProcessing = signal(false);
  reviewConfirmed = signal(false);

  wizardData = signal<WizardData>({
    sourceType: 'moodle',
    name: '',
    description: '',
    moodleUrl: '',
    moodleToken: '',
    connectionVerified: false,
    courses: [],
    selectedCourses: [],
    uploadedFiles: [],
    textEntries: [],
    forceOcr: false,
    chatbotType: 'teacher',
    customPersona: '',
    promptSuggestions: [],
    citeSources: true,
    contentTypes: {
      pdf: true,
      presentations: true,
      web: true,
      forums: false,
      scorm: false,
      glossaries: false,
      books: false,
      wiki: false,
    },
    selectedContent: [],
  });

  private getMoodleSteps(): WizardStep[] {
    return [
      {
        id: 'sourceType',
        number: 1,
        label: 'newChatbot.stepLabels.1',
        description: 'newChatbot.stepDescriptions.1',
        icon: 'icon-moodle-step-1.svg',
      },
      {
        id: 'basicInfo',
        number: 2,
        label: 'newChatbot.stepLabels.2',
        description: 'newChatbot.stepDescriptions.2',
        icon: 'icon-moodle-step-2.svg',
      },
      {
        id: 'courseSelection',
        number: 3,
        label: 'newChatbot.stepLabels.3',
        description: 'newChatbot.stepDescriptions.3',
        icon: 'icon-moodle-step-3.svg',
      },

      {
        id: 'additionalFiles',
        number: 4,
        label: 'newChatbot.stepLabels.4',
        description: 'newChatbot.stepDescriptions.4',
        icon: 'icon-moodle-step-6.svg',
      },
      {
        id: 'configuration',
        number: 5,
        label: 'newChatbot.stepLabels.5',
        description: 'newChatbot.stepDescriptions.5',
        icon: 'icon-moodle-step-4.svg',
      },
      {
        id: 'review',
        number: 6,
        label: 'newChatbot.stepLabels.6',
        description: 'newChatbot.stepDescriptions.6',
        icon: 'icon-moodle-step-7.svg',
      },
    ];
  }

  private getFileUploadSteps(): WizardStep[] {
    return [
      {
        id: 'sourceType',
        number: 1,
        label: 'newChatbot.stepLabels.1',
        description: 'newChatbot.stepDescriptions.1',
        icon: 'icon-file-step-1.svg',
      },
      {
        id: 'basicInfo',
        number: 2,
        label: 'newChatbot.stepLabels.2',
        description: 'newChatbot.stepDescriptions.2',
        icon: 'icon-file-step-2.svg',
      },
      {
        id: 'fileUpload',
        number: 3,
        label: 'newChatbot.stepLabels.7',
        description: 'newChatbot.stepDescriptions.7',
        icon: 'icon-file-step-3.svg',
      },
      {
        id: 'configuration',
        number: 4,
        label: 'newChatbot.stepLabels.5',
        description: 'newChatbot.stepDescriptions.5',
        icon: 'icon-file-step-4.svg',
      },
      {
        id: 'review',
        number: 5,
        label: 'newChatbot.stepLabels.6',
        description: 'newChatbot.stepDescriptions.6',
        icon: 'icon-file-step-5.svg',
      },
    ];
  }

  visibleSteps = computed(() => {
    const sourceType = this.wizardData().sourceType;
    return sourceType === 'moodle'
      ? this.getMoodleSteps()
      : this.getFileUploadSteps();
  });

  getCurrentStepId = computed(() => {
    const steps = this.visibleSteps();
    const step = steps.find((s) => s.number === this.currentStep());
    return step?.id || 'sourceType';
  });

  stepTitle = computed(() => {
    const steps = this.visibleSteps();
    const step = steps.find((s) => s.number === this.currentStep());
    return step?.label || '';
  });

  stepDescription = computed(() => {
    const steps = this.visibleSteps();
    const step = steps.find((s) => s.number === this.currentStep());
    return step?.description || '';
  });

  canProceed = computed(() => {
    const stepId = this.getCurrentStepId();
    const data = this.wizardData();

    switch (stepId) {
      case 'sourceType':
        return !!data.sourceType;

      case 'basicInfo':
        if (data.sourceType === 'moodle') {
          return (
            data.name.trim() !== '' &&
            data.moodleUrl.trim() !== '' &&
            data.moodleToken.trim() !== '' &&
            data.connectionVerified
          );
        } else {
          return data.name.trim() !== '';
        }

      case 'fileUpload': {
        const hasText = (data.textEntries || []).some(
          (t) => t.content.trim().length > 0
        );
        const hasCompletedFiles =
          data.uploadedFiles.length > 0 &&
          data.uploadedFiles.every((f) => f.status === 'completed');
        return hasText || hasCompletedFiles;
      }

      case 'courseSelection':
        return data.selectedCourses.length > 0;

      case 'configuration':
        return true;

      case 'additionalFiles':
        return true;

      case 'review':
        return this.reviewConfirmed();

      default:
        return false;
    }
  });

  nextStep(): void {
    if (this.canProceed() && this.currentStep() < this.visibleSteps().length) {
      this.currentStep.update((step) => step + 1);
    }
  }

  previousStep(): void {
    if (this.currentStep() > 1) {
      this.currentStep.update((step) => step - 1);
    }
  }

  goToStep(step: number): void {
    if (
      step <= this.currentStep() &&
      step >= 1 &&
      step <= this.visibleSteps().length
    ) {
      this.currentStep.set(step);
    }
  }

  goToDashboard(): void {
    if (this.hasUnsavedChanges()) {
      if (confirm(this.translate.instant('newChatbot.warningNotSaved'))) {
        this.router.navigate(['/dashboard']);
      }
    } else {
      this.router.navigate(['/dashboard']);
    }
  }

  updateWizardData(partialData: Partial<WizardData>): void {
    this.wizardData.update((data) => ({ ...data, ...partialData }));
  }

  onReviewConfirmedChange(confirmed: boolean): void {
    this.reviewConfirmed.set(confirmed);
  }
  async submitChatbot(): Promise<void> {
    if (!this.canProceed() || this.isProcessing()) return;

    this.isProcessing.set(true);

    try {
      const data = this.wizardData();

      const textEntries = (data.textEntries || [])
        .filter((t) => t.content.trim().length > 0)
        .map((t) => ({ title: t.title, content: t.content }));

      if (data.sourceType === 'files') {
        const completedFiles = data.uploadedFiles
          .filter((f) => f.status === 'completed')
          .map((f) => f.file);

        await firstValueFrom(
          this.chatbotService.createChatbotFromFiles({
            name: data.name,
            description: data.description,
            chatbotType: data.chatbotType,
            customPersona: data.chatbotType === 'custom' ? data.customPersona : undefined,
            promptSuggestions: data.promptSuggestions.filter(s => s.trim().length > 0),
            citeSources: data.citeSources,
            files: completedFiles,
            textEntries,
            forceOcr: data.forceOcr,
          })
        );
      } else {
        const additionalFiles = data.uploadedFiles
          .filter((f) => f.status === 'completed')
          .map((f) => f.file);

        await firstValueFrom(
          this.chatbotService.createChatbotFromMoodle({
            name: data.name,
            description: data.description,
            chatbotType: data.chatbotType,
            customPersona: data.chatbotType === 'custom' ? data.customPersona : undefined,
            promptSuggestions: data.promptSuggestions.filter(s => s.trim().length > 0),
            citeSources: data.citeSources,
            moodleUrl: data.moodleUrl,
            moodleToken: data.moodleToken,
            courseIds: data.selectedCourses,
            files: additionalFiles.length > 0 ? additionalFiles : undefined,
            textEntries: textEntries.length > 0 ? textEntries : undefined,
            forceOcr: data.forceOcr,
          })
        );
      }

      this.router.navigate(['/dashboard'], {
        queryParams: { created: true },
      });
    } catch (error) {
      console.error('Error creating chatbot:', error);
      alert('Failed to create chatbot. Please try again.');
    } finally {
      this.isProcessing.set(false);
    }
  }

  private hasUnsavedChanges(): boolean {
    const data = this.wizardData();
    return (
      data.name.trim() !== '' ||
      data.moodleUrl.trim() !== '' ||
      data.moodleToken.trim() !== '' ||
      data.selectedCourses.length > 0 ||
      data.uploadedFiles.length > 0 ||
      (data.textEntries || []).length > 0
    );
  }
}
