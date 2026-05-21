import {
  Component,
  input,
  output,
  ChangeDetectionStrategy,
} from '@angular/core';

import { FormsModule } from '@angular/forms';
import { TranslatePipe } from '@ngx-translate/core';
import { WizardData } from '../../new-chatbot/new-chatbot.component';

@Component({
  selector: 'app-chatbot-config-step',
  template: `
    <div class="step-container personality">
      <div class="config-form">
        <div class="config-section">
          <h3 class="section-title">
            {{ 'newChatbot.config.chatbotTypeTitle' | translate }}
          </h3>
          <p class="section-description">
            {{ 'newChatbot.config.chatbotTypeDescription' | translate }}
          </p>

          <div class="type-cards">
            <div
              class="type-card"
              [class.selected]="data().chatbotType === 'teacher'"
              (click)="updateChatbotType('teacher')"
            >                
            <img
                  class="avatar"
                  src="/icons/avatar1.png"
                  alt="Teacher"
                />
              <h4 class="type-name">
                {{ 'newChatbot.config.teacherType' | translate }}
              </h4>
              <p class="type-description">
                {{ 'newChatbot.config.teacherDescription' | translate }}
              </p>
              <ul class="type-features">
                <li>{{ 'newChatbot.config.teacherFeature1' | translate }}</li>
                <li>{{ 'newChatbot.config.teacherFeature2' | translate }}</li>
                <li>{{ 'newChatbot.config.teacherFeature3' | translate }}</li>
              </ul>
              @if(data().chatbotType === 'teacher') {
              <div class="type-badge">
                <img
                  src="/icons/check.svg"
                  alt="Selected"
                  width="16"
                  height="16"
                />
              </div>
              }
            </div>

            <div
              class="type-card"
              [class.selected]="data().chatbotType === 'studycompanion'"
              (click)="updateChatbotType('studycompanion')"
            >
              <img
                  class="avatar"
                  src="/icons/avatar2.png"
                  alt="Study Companion"
                />
              <h4 class="type-name">
                {{ 'newChatbot.config.studyBuddyType' | translate }}
              </h4>
              <p class="type-description">
                {{ 'newChatbot.config.studyBuddyDescription' | translate }}
              </p>
              <ul class="type-features">
                <li>
                  {{ 'newChatbot.config.studyBuddyFeature1' | translate }}
                </li>
                <li>
                  {{ 'newChatbot.config.studyBuddyFeature2' | translate }}
                </li>
                <li>
                  {{ 'newChatbot.config.studyBuddyFeature3' | translate }}
                </li>
              </ul>
              @if(data().chatbotType === 'studycompanion') {
              <div class="type-badge">
                <img
                  src="/icons/check.svg"
                  alt="Selected"
                  width="16"
                  height="16"
                />
              </div>
              }
            </div>
            <div
              class="type-card"
              [class.selected]="data().chatbotType === 'custom'"
              (click)="updateChatbotType('custom')"
            >
                <img
                  class="avatar"
                  src="/icons/avatar4.png"
                  alt="Custom"
                />
              <h4 class="type-name">
                {{ 'newChatbot.config.custom' | translate }}
              </h4>
              <p class="type-description" [innerHTML]="'newChatbot.config.customDescription' | translate ">
              </p>
              @if(data().chatbotType === 'custom') {
              <div class="type-badge">
                <img
                  src="/icons/check.svg"
                  alt="Selected"
                  width="16"
                  height="16"
                />
              </div>
              }
            </div>
          </div>

          @if (data().chatbotType === 'custom') {
          <div class="custom-persona-section">
            <label class="field-label">
              {{ 'newChatbot.config.customPersonaLabel' | translate }}
            </label>
            <textarea
              class="form-textarea"
              [ngModel]="data().customPersona"
              (ngModelChange)="updateCustomPersona($event)"
              placeholder="{{ 'newChatbot.config.customPersonaPlaceholder' | translate }}"
              rows="6"
              maxlength="5000"
            ></textarea>
          </div>
          }
        </div>

        <div class="config-section">
          <div class="section-title-row">
            <h3 class="section-title">
              {{ 'editChatbot.promptSuggestions' | translate }}
            </h3>
            <span class="info-tooltip">
              <img src="/icons/info.svg" alt="Info" width="14" height="14" />
              <span class="tooltip-text">{{ 'editChatbot.promptSuggestionsDescription' | translate }}</span>
            </span>
          </div>

          <div class="suggestions-edit-list">
            @for (suggestion of data().promptSuggestions; track $index) {
            <div class="suggestion-edit-row">
              <input
                type="text"
                class="form-input"
                [value]="suggestion"
                (input)="updateSuggestion($index, $any($event.target).value)"
                [placeholder]="'editChatbot.suggestionPlaceholder' | translate"
                maxlength="150"
              />
              <button
                class="btn-icon btn-remove"
                (click)="removeSuggestion($index)"
                title="Remove"
              >
                <img
                  src="/icons/x-circle.svg"
                  alt="Remove"
                  width="16"
                  height="16"
                />
              </button>
            </div>
            }
          </div>
          @if (data().promptSuggestions.length < 4) {
          <button class="btn btn-ghost btn-sm" (click)="addSuggestion()">
            + {{ 'editChatbot.addSuggestion' | translate }}
          </button>
          } @else {
          <span class="field-hint">{{ 'editChatbot.maxSuggestions' | translate }}</span>
          }
        </div>

        <div class="config-section">
          <label class="toggle-row">
            <input
              type="checkbox"
              [ngModel]="data().citeSources"
              (ngModelChange)="updateCiteSources($event)"
            />
            <span class="toggle-label">
              {{ 'newChatbot.config.citeSources' | translate }}
            </span>
            <span class="info-tooltip">
              <img src="/icons/info.svg" alt="Info" width="14" height="14" />
              <span class="tooltip-text">{{ 'newChatbot.config.citeSourcesDescription' | translate }}</span>
            </span>
          </label>
        </div>
      </div>
    </div>
  `,
  styleUrl: './chatbot-config-step.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [FormsModule, TranslatePipe],
})
export class ChatbotConfigStepComponent {
  data = input.required<WizardData>();
  dataChange = output<Partial<WizardData>>();

  updateChatbotType(chatbotType: 'teacher' | 'studycompanion' | 'custom'): void {
    this.dataChange.emit({ chatbotType });
  }

  updateCustomPersona(customPersona: string): void {
    this.dataChange.emit({ customPersona });
  }

  updateCiteSources(citeSources: boolean): void {
    this.dataChange.emit({ citeSources });
  }

  addSuggestion(): void {
    const current = this.data().promptSuggestions;
    if (current.length < 4) {
      this.dataChange.emit({ promptSuggestions: [...current, ''] });
    }
  }

  removeSuggestion(index: number): void {
    const current = this.data().promptSuggestions;
    this.dataChange.emit({ promptSuggestions: current.filter((_, i) => i !== index) });
  }

  updateSuggestion(index: number, value: string): void {
    const current = [...this.data().promptSuggestions];
    current[index] = value;
    this.dataChange.emit({ promptSuggestions: current });
  }
}
