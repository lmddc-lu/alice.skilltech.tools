import {
  Component,
  ChangeDetectionStrategy,
  signal,
  computed,
  input,
  output,
  effect,
} from '@angular/core';

import { FormsModule } from '@angular/forms';
import { TranslatePipe } from '@ngx-translate/core';

export interface TextEntrySaveEvent {
  title: string;
  content: string;
}

@Component({
  selector: 'app-text-entry-dialog',
  imports: [FormsModule, TranslatePipe],
  changeDetection: ChangeDetectionStrategy.OnPush,
  styleUrl: './text-entry-dialog.component.scss',
  template: `
    <div class="modal-overlay" (click)="onOverlayClick($event)">
      <div class="modal-container text-entry-dialog" (click)="$event.stopPropagation()">
        <div class="modal-header">
          <h2>
            {{
              (mode() === 'edit'
                ? 'textEntry.editTitle'
                : 'textEntry.createTitle') | translate
            }}
          </h2>
          <button
            type="button"
            class="close-button"
            [attr.aria-label]="'textEntry.close' | translate"
            (click)="cancel()"
          >
            <svg width="24" height="24" viewBox="0 0 24 24" fill="none"
                 stroke="currentColor" stroke-width="2" aria-hidden="true">
              <path d="M18 6L6 18M6 6l12 12" />
            </svg>
          </button>
        </div>

        <div class="modal-content text-entry-content">
          @if (isLoading()) {
            <div class="loading-state" role="status" aria-live="polite">
              <div class="spinner" aria-hidden="true"></div>
              <p>{{ 'textEntry.loading' | translate }}</p>
            </div>
          } @else {
            <label class="field">
              <span class="field-label">{{ 'textEntry.titleLabel' | translate }}</span>
              <input
                type="text"
                class="field-input"
                [placeholder]="'textEntry.titlePlaceholder' | translate"
                [ngModel]="title()"
                (ngModelChange)="title.set($event)"
                maxlength="120"
                [disabled]="isSaving()"
              />
            </label>

            <label class="field field-grow">
              <span class="field-label">{{ 'textEntry.contentLabel' | translate }}</span>
              <textarea
                class="field-textarea"
                [placeholder]="'textEntry.contentPlaceholder' | translate"
                [ngModel]="content()"
                (ngModelChange)="content.set($event)"
                [disabled]="isSaving()"
              ></textarea>
            </label>

            <p class="field-hint">{{ 'textEntry.hint' | translate }}</p>
          }
        </div>

        <div class="modal-footer">
          <button
            type="button"
            class="btn btn-secondary"
            (click)="cancel()"
            [disabled]="isSaving()"
          >
            {{ 'textEntry.cancel' | translate }}
          </button>
          <button
            type="button"
            class="btn btn-primary"
            (click)="submit()"
            [disabled]="!canSave() || isSaving() || isLoading()"
          >
            @if (isSaving()) {
              <span class="button-spinner" aria-hidden="true"></span>
              {{ 'textEntry.saving' | translate }}
            } @else {
              {{ 'textEntry.save' | translate }}
            }
          </button>
        </div>
      </div>
    </div>
  `,
})
export class TextEntryDialogComponent {
  mode = input<'create' | 'edit'>('create');
  initialTitle = input<string>('');
  initialContent = input<string>('');
  isLoading = input<boolean>(false);
  isSaving = input<boolean>(false);
  // Parent bumps this to re-seed title/content; without it the effect would
  // overwrite the user's typing whenever inputs changed.
  resetToken = input<number>(0);

  close = output<void>();
  save = output<TextEntrySaveEvent>();

  title = signal<string>('');
  content = signal<string>('');

  canSave = computed(() => this.content().trim().length > 0);

  constructor() {
    effect(() => {
      this.resetToken();
      this.title.set(this.initialTitle());
      this.content.set(this.initialContent());
    });
  }

  onOverlayClick(event: MouseEvent): void {
    if (event.target === event.currentTarget && !this.isSaving()) {
      this.cancel();
    }
  }

  cancel(): void {
    if (this.isSaving()) return;
    this.close.emit();
  }

  submit(): void {
    if (!this.canSave() || this.isSaving()) return;
    this.save.emit({
      title: this.title().trim(),
      content: this.content(),
    });
  }
}
