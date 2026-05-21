import {
  Component,
  input,
  output,
  signal,
  ChangeDetectionStrategy,
} from '@angular/core';

import { FormsModule } from '@angular/forms';
import { TranslatePipe } from '@ngx-translate/core';

export type AccessDialogType =
  | 'disabled'
  | 'password'
  | 'error'
  | 'private'
  | 'loading'
  | 'processing';

@Component({
  selector: 'app-chat-access-dialog',
  standalone: true,
  imports: [FormsModule, TranslatePipe],
  template: `
    <div class="access-dialog-container">
      <div class="access-dialog">
        <div class="dialog-icon" [class]="dialogType()">
          @switch (dialogType()) { @case ('loading') {
          <div class="loading-spinner"></div>
          } @case ('processing') {
          <div class="loading-spinner"></div>
          } @case ('disabled') {
          <img src="/icons/icon_cross2.svg" alt="" width="48" height="48" />
          } @case ('password') {
          <img src="/icons/icon_lock.svg" alt="" width="48" height="48" />
          } @case ('private') {
          <img src="/icons/icon_lock.svg" alt="" width="48" height="48" />
          } @case ('error') {
          <img src="/icons/icon_alert.svg" alt="" width="48" height="48" />
          } }
        </div>

        <h2 class="dialog-title">
          @switch (dialogType()) { @case ('loading') {
          {{ 'chatAccess.loading.title' | translate }}
          } @case ('processing') {
          {{ 'chatAccess.processing.title' | translate }}
          } @case ('disabled') {
          {{ 'chatAccess.disabled.title' | translate }}
          } @case ('password') {
          {{ 'chatAccess.password.title' | translate }}
          } @case ('private') {
          {{ 'chatAccess.private.title' | translate }}
          } @case ('error') {
          {{ 'chatAccess.error.title' | translate }}
          } }
        </h2>


        <p class="dialog-description">
          @switch (dialogType()) { @case ('loading') {
          {{ 'chatAccess.loading.description' | translate }}
          } @case ('processing') {
          {{ 'chatAccess.processing.description' | translate }}
          } @case ('disabled') {
          {{ 'chatAccess.disabled.description' | translate }}
          } @case ('password') {
          {{ 'chatAccess.password.description' | translate }}
          } @case ('private') {
          {{ 'chatAccess.private.description' | translate }}
          } @case ('error') {
          {{ (errorMessage() || 'chatAccess.error.description') | translate }}
          } }
        </p>

        @if (dialogType() === 'password') {
        <div class="password-form">
          @if (passwordError()) {
          <div class="password-error">
            <img src="/icons/x-circle.svg" alt="" width="16" height="16" />
            <span>{{ passwordError() | translate }}</span>
          </div>
          }
          <div class="form-group">
            <input
              type="password"
              class="form-input"
              [(ngModel)]="passwordValue"
              (keyup.enter)="onSubmitPassword()"
              [placeholder]="'chatAccess.password.placeholder' | translate"
              [disabled]="isSubmitting()"
              autofocus
            />
          </div>
        </div>
        }

        <div class="dialog-actions">
          @switch (dialogType()) { @case ('loading') {
          } @case ('processing') {
          } @case ('disabled') {
         
          } @case ('password') {
         
          <button
            class="btn btn-primary"
            (click)="onSubmitPassword()"
            [disabled]="!passwordValue().trim() || isSubmitting()"
          >
            @if (isSubmitting()) {
            <div class="loading-spinner small"></div>
            {{ 'chatAccess.actions.checking' | translate }}
            } @else {
            {{ 'chatAccess.actions.submit' | translate }}
            }
          </button>
          } @case ('private') {
          <button class="btn btn-primary" (click)="onLogin()">
            {{ 'chatAccess.actions.login' | translate }}
          </button>
          } @case ('error') {
          } }
        </div>
      </div>
    </div>
  `,
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class ChatAccessDialogComponent {
  dialogType = input.required<AccessDialogType>();
  errorMessage = input<string | null>(null);
  passwordError = input<string | null>(null);
  isSubmitting = input<boolean>(false);

  submitPassword = output<string>();
  cancel = output<void>();
  login = output<void>();

  passwordValue = signal('');

  onSubmitPassword(): void {
    const password = this.passwordValue().trim();
    if (password && !this.isSubmitting()) {
      this.submitPassword.emit(password);
    }
  }

  onCancel(): void {
    this.passwordValue.set('');
    this.cancel.emit();
  }

  onLogin(): void {
    this.login.emit();
  }
}
