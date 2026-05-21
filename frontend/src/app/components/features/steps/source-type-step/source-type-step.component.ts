import {
  Component,
  input,
  output,
  ChangeDetectionStrategy,
} from '@angular/core';

import { TranslatePipe } from '@ngx-translate/core';
import { WizardData } from '../../new-chatbot/new-chatbot.component';

@Component({
  selector: 'app-source-type-step',
  template: `
    <div class="step-container">
      <div class="source-type-selection">
        <div
          class="source-type-card"
          [class.selected]="data().sourceType === 'moodle'"
          (click)="selectSourceType('moodle')"
        >
          <div class="card-header">
            <div class="source-icon moodle">
              <img
                src="/icons/logo_moodle.svg"
                [alt]="'newChatbot.sourceType.moodle.title' | translate"
                width="48"
                height="48"
              />
            </div>
            <h3 class="source-title">
              {{ 'newChatbot.sourceType.moodle.title' | translate }}
            </h3>
          </div>

          <div class="card-body">
            <p class="source-description">
              {{ 'newChatbot.sourceType.moodle.description' | translate }}
            </p>

            <ul class="feature-list">
              <li>
                <img
                  src="/icons/icon_check_yellow.svg"
                  alt="Check"
                  width="16"
                  height="16"
                />
                <span>{{
                  'newChatbot.sourceType.moodle.feature1' | translate
                }}</span>
              </li>
              <li>
                <img
                  src="/icons/icon_check_yellow.svg"
                  alt="Check"
                  width="16"
                  height="16"
                />
                <span>{{
                  'newChatbot.sourceType.moodle.feature2' | translate
                }}</span>
              </li>
              <li>
                <img
                  src="/icons/icon_check_yellow.svg"
                  alt="Check"
                  width="16"
                  height="16"
                />
                <span>{{
                  'newChatbot.sourceType.moodle.feature4' | translate
                }}</span>
              </li>
            </ul>
            <ul class="feature-list more">
              <li>
                <img
                  src="/icons/icon_plus.svg"
                  alt="Add more"
                  width="16"
                  height="16"
                />
                <span
                  [innerHTML]="'newChatbot.sourceType.additionalFilesNote' | translate"
                ></span>
              </li>

              <li></li>
            </ul>
          </div>

          @if (data().sourceType === 'moodle') {
          <div class="selected-badge">
            <img
              src="/icons/icon_check.svg"
              [alt]="'newChatbot.sourceType.selected' | translate"
              width="16"
              height="16"
            />
            <span>{{ 'newChatbot.sourceType.selected' | translate }}</span>
          </div>
          }
        </div>

        <div
          class="source-type-card"
          [class.selected]="data().sourceType === 'files'"
          (click)="selectSourceType('files')"
        >
          <div class="card-header">
            <div class="source-icon files">
              <img
                src="/icons/icon_upload.svg"
                [alt]="'newChatbot.sourceType.files.title' | translate"
                width="48"
                height="48"
              />
            </div>
            <h3 class="source-title">
              {{ 'newChatbot.sourceType.files.title' | translate }}
            </h3>
          </div>

          <div class="card-body">
            <p class="source-description">
              {{ 'newChatbot.sourceType.files.description' | translate }}
            </p>

            <ul class="feature-list">
              <li>
                <img
                  src="/icons/icon_check_blue.svg"
                  alt="Check"
                  width="16"
                  height="16"
                />
                <span>{{
                  'newChatbot.sourceType.files.feature1' | translate
                }}</span>
              </li>
              <li>
                <img
                  src="/icons/icon_check_blue.svg"
                  alt="Check"
                  width="16"
                  height="16"
                />
                <span>{{
                  'newChatbot.sourceType.files.feature3' | translate
                }}</span>
              </li>
              <li>
                <img
                  src="/icons/icon_check_blue.svg"
                  alt="Check"
                  width="16"
                  height="16"
                />
                <span>{{
                  'newChatbot.sourceType.files.feature4' | translate
                }}</span>
              </li>
            </ul>
          </div>

          @if (data().sourceType === 'files') {
          <div class="selected-badge">
            <img
              src="/icons/icon_check.svg"
              [alt]="'newChatbot.sourceType.selected' | translate"
              width="16"
              height="16"
            />
            <span>{{ 'newChatbot.sourceType.selected' | translate }}</span>
          </div>
          }
        </div>
      </div>
    </div>
  `,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [TranslatePipe],
})
export class SourceTypeStepComponent {
  data = input.required<WizardData>();
  dataChange = output<Partial<WizardData>>();

  selectSourceType(sourceType: 'moodle' | 'files'): void {
    if (this.data().sourceType === sourceType) {
      return;
    }

    const updates: Partial<WizardData> = { sourceType };

    if (sourceType === 'moodle') {
      updates.uploadedFiles = [];
    } else {
      updates.moodleUrl = '';
      updates.moodleToken = '';
      updates.connectionVerified = false;
      updates.courses = [];
      updates.selectedCourses = [];
      updates.selectedContent = [];
      updates.contentTypes = {
        pdf: true,
        presentations: true,
        web: true,
        forums: false,
        scorm: false,
        glossaries: false,
        books: false,
        wiki: false,
      };
    }

    this.dataChange.emit(updates);
  }
}
