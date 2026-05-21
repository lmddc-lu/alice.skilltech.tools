import {
  Component,
  input,
  output,
  signal,
  inject,
  OnInit,
  computed,
  effect,
  ChangeDetectionStrategy,
} from '@angular/core';

import { FormBuilder, ReactiveFormsModule, Validators } from '@angular/forms';
import { TranslatePipe } from '@ngx-translate/core';
import { HttpClient } from '@angular/common/http';
import { WizardData } from '../../new-chatbot/new-chatbot.component';
import { environment } from '../../../../../environments/environment';
import { firstValueFrom } from 'rxjs';


interface MoodleConnectionResponse {
  success: boolean;
  total_courses?: number;
  plugin_installed?: boolean;
  message?: string;
  error?: string;
}

@Component({
  selector: 'app-basic-info-step',
  template: `
    <div class="step-container">
      <form [formGroup]="form" class="wizard-form">
        <div class="form-group">
          <label class="form-label required">
            {{ 'newChatbot.basicInfo.name' | translate }}
          </label>
          <input
            type="text"
            class="form-control"
            formControlName="name"
            [placeholder]="'newChatbot.basicInfo.namePlaceholder' | translate"
            maxlength="100"
          />
          @if (form.get('name')?.invalid && form.get('name')?.touched) {
          <span class="form-error">
            {{ 'newChatbot.basicInfo.nameRequired' | translate }}
          </span>
          }
        </div>
        <div class="form-group">
          <label class="form-label"> Description </label>
          <textarea
            type="text"
            class="form-control"
            formControlName="description"
            maxlength="300"
            rows="5"
            [placeholder]="'newChatbot.basicInfo.descriptionPlaceholder' | translate"
          >
          </textarea>
        </div>

        @if (isMoodleFlow()) {
        <div class="form-group">
          <label class="form-label required">
            {{ 'newChatbot.basicInfo.moodleUrl' | translate }}
          </label>
          <input
            type="url"
            class="form-control"
            formControlName="moodleUrl"
            [placeholder]="
              'newChatbot.basicInfo.moodleUrlPlaceholder' | translate
            "
          />
          @if (form.get('moodleUrl')?.invalid && form.get('moodleUrl')?.touched)
          {
          <span class="form-error">
            {{ 'newChatbot.basicInfo.moodleUrlRequired' | translate }}
          </span>
          }
        </div>

        <div class="form-group">
          <label class="form-label required">
            {{ 'newChatbot.basicInfo.moodleToken' | translate }}
          </label>
          <div class="input-with-action">
            <input
              [type]="showToken() ? 'text' : 'password'"
              class="form-control"
              formControlName="moodleToken"
              [placeholder]="
                'newChatbot.basicInfo.moodleTokenPlaceholder' | translate
              "
            />
            <button
              type="button"
              class="btn btn-ghost btn-sm"
              (click)="toggleTokenVisibility()"
            >
              <img
                [src]="showToken() ? '/icons/eye-off.svg' : '/icons/eye.svg'"
                [alt]="showToken() ? 'Hide' : 'Show'"
                width="16"
                height="16"
              />
            </button>
          </div>
          @if (form.get('moodleToken')?.invalid &&
          form.get('moodleToken')?.touched) {
          <span class="form-error">
            {{ 'newChatbot.basicInfo.moodleTokenRequired' | translate }}
          </span>
          }
        </div>

        <div class="form-group">
          <div class="connection-status">
            @if (isVerifying()) {
            <div class="status-message verifying">
              <div class="loading-spinner small"></div>
              {{ 'newChatbot.basicInfo.verifying' | translate }}
            </div>
            } @else if (connectionStatus() === 'success') {
            <div class="status-message success">
              <img
                src="/icons/icon_check3.svg"
                alt="Success"
                width="16"
                height="16"
              />
              <div>
                {{ 'newChatbot.basicInfo.connectionSuccess' | translate }}
              </div>
            </div>
            } @else if (connectionStatus() === 'error') {
            <div class="status-message error">
              <img
                src="/icons/icon_cross.svg"
                alt="Error"
                width="16"
                height="16"
              />
              {{
                connectionError() ||
                  ('newChatbot.basicInfo.connectionError' | translate)
              }}
            </div>
            }

            <button
              type="button"
              class="btn btn-primary"
              (click)="verifyConnection()"
              [disabled]="!canVerify() || isVerifying()"
            >
              <img
                src="/icons/refresh.svg"
                alt="Verify"
                width="16"
                height="16"
              />
              {{ 'newChatbot.basicInfo.verifyConnection' | translate }}
            </button>
          </div>
        </div>

        <div class="help-text">
          <img src="/icons/info.svg" alt="Info" width="16" height="16" />
          <p [innerHTML]="'newChatbot.basicInfo.helpText' | translate"></p>
        </div>
        }
      </form>
    </div>
  `,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [ReactiveFormsModule, TranslatePipe],
})
export class BasicInfoStepComponent implements OnInit {
  private fb = inject(FormBuilder);
  private http = inject(HttpClient);

  data = input.required<WizardData>();
  dataChange = output<Partial<WizardData>>();

  showToken = signal(false);
  isVerifying = signal(false);
  connectionStatus = signal<'idle' | 'success' | 'error'>('idle');
  connectionError = signal<string | null>(null);
  connectionDetails = signal<MoodleConnectionResponse | null>(null);

  private formValid = signal(false);

  isMoodleFlow = computed(() => {
    const sourceType = this.data().sourceType;
    return sourceType === 'moodle';
  });

  canVerify = computed(() => {
    if (!this.isMoodleFlow()) return false;

    // Read formValid so this computed re-runs on form validity changes.
    this.formValid();

    const moodleUrlControl = this.form.get('moodleUrl');
    const moodleTokenControl = this.form.get('moodleToken');

    return moodleUrlControl?.valid && moodleTokenControl?.valid;
  });

  form = this.fb.group({
    name: ['', [Validators.required, Validators.minLength(3)]],
    description: [''],
    moodleUrl: [''],
    moodleToken: [''],
  });

  constructor() {
    effect(() => {
      const isMoodle = this.isMoodleFlow();
      this.updateFormValidators(isMoodle);
    });
  }

  ngOnInit(): void {
    const currentData = this.data();

    if (currentData) {
      if (currentData.connectionVerified) {
        this.connectionStatus.set('success');
      }
    }

    this.form.valueChanges.subscribe((values) => {
      this.formValid.set(this.form.valid);

      const updates: Partial<WizardData> = {
        name: values.name || '',
        description: values.description || '',
      };

      if (this.isMoodleFlow()) {
        updates.moodleUrl = values.moodleUrl || '';
        updates.moodleToken = values.moodleToken || '';
        updates.connectionVerified = this.connectionStatus() === 'success';
      }

      this.dataChange.emit(updates);
    });

    this.formValid.set(this.form.valid);
  }

  private updateFormValidators(isMoodle: boolean): void {
    const moodleUrlControl = this.form.get('moodleUrl');
    const moodleTokenControl = this.form.get('moodleToken');

    if (isMoodle) {
      moodleUrlControl?.setValidators([
        Validators.required,
        Validators.pattern('https?://.+'),
      ]);
      moodleTokenControl?.setValidators([Validators.required]);
    } else {
      moodleUrlControl?.clearValidators();
      moodleTokenControl?.clearValidators();

      moodleUrlControl?.setValue('');
      moodleTokenControl?.setValue('');
    }

    moodleUrlControl?.updateValueAndValidity();
    moodleTokenControl?.updateValueAndValidity();

    this.formValid.set(this.form.valid);
  }

  toggleTokenVisibility(): void {
    this.showToken.update((show) => !show);
  }

  async verifyConnection(): Promise<void> {
    if (!this.canVerify() || this.isVerifying()) return;

    this.isVerifying.set(true);
    this.connectionStatus.set('idle');
    this.connectionError.set(null);
    this.connectionDetails.set(null);

    try {
      const { moodleUrl, moodleToken } = this.form.value;

      if (!moodleUrl || !moodleToken) {
        throw new Error('Moodle URL and token are required');
      }

      const response = await firstValueFrom(
        this.http.post<MoodleConnectionResponse>(
          `${environment.apiBaseUrl}/moodle/test-connection`,
          {
            moodle_url: moodleUrl,
            token: moodleToken,
          }
        )
      );
      if (response?.success) {
        this.connectionStatus.set('success');
        this.connectionDetails.set(response);
        this.dataChange.emit({ connectionVerified: true });
      } else {
        throw new Error(response?.error || 'Connection failed');
      }
    } catch (error: any) {
      console.error('Moodle connection error:', error);
      this.connectionStatus.set('error');

      let errorMessage =
        'Failed to connect to Moodle. Please check your URL and token.';

      if (error?.error?.error) {
        errorMessage = error.error.error;
      } else if (error?.message) {
        errorMessage = error.message;
      }

      if (error?.error?.error_code === 'invalidtoken') {
        errorMessage =
          'Invalid token. Please check your Moodle token and try again.';
      } else if (error?.error?.error_code === 'connectionerror') {
        errorMessage =
          'Could not connect to the Moodle site. Please check the URL.';
      }

      this.connectionError.set(errorMessage);
      this.dataChange.emit({ connectionVerified: false });
    } finally {
      this.isVerifying.set(false);
    }
  }
}
