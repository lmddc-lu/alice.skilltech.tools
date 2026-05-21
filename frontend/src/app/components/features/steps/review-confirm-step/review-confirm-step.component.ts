import {
  Component,
  input,
  output,
  computed,
  ChangeDetectionStrategy,
} from '@angular/core';

import { FormsModule } from '@angular/forms';
import { TranslatePipe } from '@ngx-translate/core';
import { WizardData } from '../../new-chatbot/new-chatbot.component';

@Component({
  selector: 'app-review-confirm-step',
  template: `
    <div class="step-container">
      <div class="review-content">
        <div class="review-sections">
          <div class="review-section">
            <h4 class="section-title">
              {{ 'newChatbot.review.basicInfo' | translate }}
            </h4>
            <div class="review-items">
              <div class="infos">
                <div class="review-item">
                  <span class="item-label">{{
                    'newChatbot.review.chatbotName' | translate
                  }}</span>
                  <span class="item-value">{{ data().name }}</span>
                </div>
                <div class="review-item">
                  <span class="item-label">Description:</span>
                  <span class="item-value"
                    > {{data().description}}</span
                  >
                </div>
              </div>
              @if (data().sourceType === 'moodle') {
              <div class="review-item">
                <span class="item-label">{{
                  'newChatbot.review.moodleUrl' | translate
                }}</span>
                <span class="item-value">{{ data().moodleUrl }}</span>
              </div>
              <div class="review-item">
                <span class="item-label">{{
                  'newChatbot.review.connectionStatus' | translate
                }}</span>
                <span class="item-value status-verified">
                  <img
                    src="/icons/check-circle.svg"
                    alt="Verified"
                    width="16"
                    height="16"
                  />
                  {{ 'newChatbot.review.verified' | translate }}
                </span>
              </div>
              }
            </div>
          </div>

          @if (data().sourceType === 'moodle') {
          <div class="review-section">
            <h4 class="section-title">
              {{ 'newChatbot.review.courseSelection' | translate }}
            </h4>
            <div class="review-items">
              <div class="review-item">
                <span class="item-label">{{
                  'newChatbot.review.selectedCourses' | translate
                }}</span>
                <span class="item-value">
                  {{ selectedCoursesCount() }}
                  {{ 'newChatbot.review.courses' | translate }}
                </span>
              </div>
              <div class="course-list">
                @for (course of selectedCourses(); track course.id) {
                <span class="course-tag">{{ course.shortname }}</span>
                }
              </div>
            </div>
          </div>
          }

          @if (reviewItemsTotal() > 0) {
          <div class="review-section">
            <h4 class="section-title">
              @if (data().sourceType === 'moodle') { Additional Files } @else {
              {{ 'newChatbot.review.uploadedFiles' | translate }}
              }
            </h4>
            <div class="review-items">
              <div class="review-item">
                <span class="item-label">{{
                  'newChatbot.review.totalFiles' | translate
                }}</span>
                <span class="item-value"
                  >{{ reviewItemsTotal() }}
                  {{ 'newChatbot.review.files' | translate }}</span
                >
              </div>
              <div class="review-item">
                <span class="item-label">{{
                  'newChatbot.review.totalSize' | translate
                }}</span>
                <span class="item-value">{{
                  formatSize(uploadedFilesSize())
                }}</span>
              </div>

              <div class="file-preview-list">
                @for (entry of (data().textEntries || []).slice(0, 5); track entry.id) {
                <div class="file-preview-item">
                  <img src="/icons/file.svg" alt="Text" width="16" height="16" />
                  <span class="file-name">
                    {{ entry.title || ('textEntry.untitled' | translate) }}
                  </span>
                  <span class="file-size">{{ entry.content.length }} chars</span>
                </div>
                }
                @for (file of data().uploadedFiles.slice(0, 5); track file.name)
                {
                <div class="file-preview-item">
                  <img
                    [src]="getFileIcon(file.type)"
                    alt="File"
                    width="16"
                    height="16"
                  />
                  <span class="file-name">{{ file.name }}</span>
                  <span class="file-size">{{ formatSize(file.size) }}</span>
                </div>
                } @if (reviewItemsTotal() > 10) {
                <div class="file-preview-more">
                  +{{ reviewItemsTotal() - 10 }}
                  {{ 'newChatbot.review.moreFiles' | translate }}
                </div>
                }
              </div>
            </div>
          </div>
          }

          <div class="review-section">
            <h4 class="section-title">
              {{ 'newChatbot.review.configuration' | translate }}
            </h4>
            <div class="review-items">
              <div class="review-item">
                <div class="avatar">
                  @if (data().chatbotType === 'teacher') {
                    <img src="/icons/avatar1.png" alt="Teacher" />
                  } @else if (data().chatbotType === 'studycompanion') {
                    <img src="/icons/avatar2.png" alt="Study Companion" />
                  } @else {
                    <img src="/icons/avatar4.png" alt="Custom" />
                  }
                </div>
                <div class="description">
                  <span class="item-label">{{
                    'newChatbot.review.chatbotType' | translate
                  }}</span>
                  <span class="item-value">
                    @if (data().chatbotType === 'teacher') {
                    {{ 'newChatbot.review.teacherType' | translate }}
                    } @else if (data().chatbotType === 'studycompanion') {
                    {{ 'newChatbot.review.studyBuddyType' | translate }}
                    } @else {
                    {{ 'newChatbot.review.customType' | translate }}
                    }
                  </span>
                </div>
              </div>
            </div>
          </div>

          @if (data().sourceType === 'moodle' && data().uploadedFiles.length >
          0) {
          <div class="review-section">
            <h4 class="section-title">Content Summary</h4>
            <div class="review-items">
              <div class="content-summary-grid">
                <div class="summary-card">
                  <div class="summary-icon moodle">
                    <img
                      src="/icons/package.svg"
                      alt="Moodle"
                      width="24"
                      height="24"
                    />
                  </div>
                  <div class="summary-info">
                    <div class="summary-value">{{ totalSelectedItems() }}</div>
                    <div class="summary-label">Moodle Content Items</div>
                  </div>
                </div>
                <div class="summary-card">
                  <div class="summary-icon files">
                    <img
                      src="/icons/file.svg"
                      alt="Files"
                      width="24"
                      height="24"
                    />
                  </div>
                  <div class="summary-info">
                    <div class="summary-value">
                      {{ data().uploadedFiles.length }}
                    </div>
                    <div class="summary-label">Additional Files</div>
                  </div>
                </div>
              </div>
            </div>
          </div>
          }
        </div>

        @if (!isProcessing()) {
        <div class="processing-notice">
          <div class="notice-icon">
            <img src="/icons/info.svg" alt="Info" width="20" height="20" />
          </div>
          <div class="notice-content">
            <h5>{{ 'newChatbot.review.processingTitle' | translate }}</h5>
            <p>
              {{ 'newChatbot.review.processingDescription' | translate }}
            </p>
            <ul>
              @if (data().sourceType === 'moodle') {
              <li>{{ 'newChatbot.review.processingStep1' | translate }}</li>
              <li>{{ 'newChatbot.review.processingStep2' | translate }}</li>
              @if (data().uploadedFiles.length > 0) {
              <li>
                Processing {{ data().uploadedFiles.length }} additional files
              </li>
              } } @else {
              <li>
                {{ 'newChatbot.review.processingStep1Files' | translate }}
              </li>
              <li>
                {{ 'newChatbot.review.processingStep2Files' | translate }}
              </li>
              }
              <li>
                {{ 'newChatbot.review.processingStep3Files' | translate }}
              </li>
            </ul>
          </div>
        </div>
        } @else {
        <div class="processing-status">
          <div class="loading-spinner"></div>
          <h5>{{ 'newChatbot.review.creatingChatbot' | translate }}</h5>
          <p>{{ 'newChatbot.review.pleaseWait' | translate }}</p>
        </div>
        }

        @if (!isProcessing()) {
        <div class="confirmation-section">
          <label class="confirmation-checkbox">
            <input type="checkbox" class="st2" [ngModel]="confirmed" (ngModelChange)="onConfirmedChange($event)" />
            <span>{{ 'newChatbot.review.confirmationText' | translate }}</span>
          </label>
        </div>
        }
      </div>
    </div>
  `,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [TranslatePipe, FormsModule],
})
export class ReviewConfirmStepComponent {
  data = input.required<WizardData>();
  isProcessing = input.required<boolean>();

  confirmedChange = output<boolean>();

  confirmed = false;

  onConfirmedChange(value: boolean): void {
    this.confirmed = value;
    this.confirmedChange.emit(value);
  }

  selectedCourses = computed(() => {
    const data = this.data();
    return data.courses.filter((course) =>{
      return data.selectedCourses.includes(course.id.toString());
    }
    );
  });

  selectedCoursesCount = computed(() => this.selectedCourses().length);

  selectedContentTypes = computed(() => {
    const types = this.data().contentTypes;
    const selected: string[] = [];

    if (types.pdf) selected.push('PDF');
    if (types.presentations) selected.push('Presentations');
    if (types.web) selected.push('Web Content');
    if (types.forums) selected.push('Forums');
    if (types.scorm) selected.push('SCORM');
    if (types.glossaries) selected.push('Glossaries');
    if (types.books) selected.push('Books');
    if (types.wiki) selected.push('Wiki');

    return selected;
  });

  totalSelectedItems = computed(() => {
    return this.data().selectedContent.reduce(
      (total, course) =>
        total + course.items.filter((item) => item.selected).length,
      0
    );
  });

  totalContentSize = computed(() => {
    return this.data().selectedContent.reduce(
      (total, course) =>
        total +
        course.items
          .filter((item) => item.selected)
          .reduce((sum, item) => sum + (item.size || 0), 0),
      0
    );
  });

  uploadedFilesSize = computed(() => {
    const filesSize = this.data().uploadedFiles.reduce(
      (total, file) => total + file.size,
      0
    );
    // Approximate text bytes as char count (UTF-8 downstream).
    const textSize = (this.data().textEntries || []).reduce(
      (total, entry) => total + entry.content.length,
      0
    );
    return filesSize + textSize;
  });

  reviewItemsTotal = computed(
    () =>
      this.data().uploadedFiles.length + (this.data().textEntries || []).length
  );

  totalContentItems = computed(() => {
    return this.totalSelectedItems() + this.reviewItemsTotal();
  });

  formatSize(bytes: number): string {
    if (bytes === 0) return '0 Bytes';
    const k = 1024;
    const sizes = ['Bytes', 'KB', 'MB', 'GB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return Math.round((bytes / Math.pow(k, i)) * 100) / 100 + ' ' + sizes[i];
  }

  getFileIcon(type: string): string {
    if (type.includes('pdf')) return '/icons/file.svg';
    if (type.includes('word')) return '/icons/file.svg';
    if (type.includes('powerpoint') || type.includes('presentation'))
      return '/icons/monitor.svg';
    return '/icons/file.svg';
  }
}
