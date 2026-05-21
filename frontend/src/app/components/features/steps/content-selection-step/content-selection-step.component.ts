import {
  Component,
  input,
  output,
  signal,
  computed,
  OnInit,
  inject,
  ChangeDetectionStrategy,
} from '@angular/core';

import { FormsModule } from '@angular/forms';
import { TranslatePipe } from '@ngx-translate/core';
import { HttpClient } from '@angular/common/http';
import {
  WizardData,
  SelectedContent,
} from '../../new-chatbot/new-chatbot.component';

interface ContentType {
  key: keyof WizardData['contentTypes'];
  label: string;
  icon: string;
  description: string;
  isAlpha?: boolean;
}

@Component({
  selector: 'app-content-selection-step',
  template: `
    <div class="step-container content">
      <div class="content-types-section">
        <h3 class="section-title">
          {{ 'newChatbot.content.typesTitle' | translate }}
        </h3>
        <p class="section-description">
          {{ 'newChatbot.content.typesDescription' | translate }}
        </p>

        <div class="content-types-grid">
          @for (type of contentTypes; track type.key) {
          <label
            class="content-type-card"
            [class.selected]="data().contentTypes[type.key]"
          >
            <input
              type="checkbox"
              class="st1"
              [checked]="data().contentTypes[type.key]"
              (change)="toggleContentType(type.key)"
            />
            <div class="type-icon">
              <img
                [src]="'/icons/' + type.icon + '.svg'"
                [alt]="type.label"
                width="24"
                height="24"
              />
            </div>
            <span class="type-label">{{ type.label | translate }}</span>
            @if (type.isAlpha) {
            <span class="alpha-badge">{{
              'newChatbot.content.alpha' | translate
            }}</span>
            }
          </label>
          }
        </div>
      </div>

      @if (hasSelectedTypes()) {
      <div class="content-preview-section">
        <h3 class="section-title">
          {{ 'newChatbot.content.previewTitle' | translate }}
        </h3>
        <p class="section-description">
          {{ 'newChatbot.content.previewDescription' | translate }}
        </p>

        @if (isLoadingContent()) {
        <div class="loading-state">
          <div class="loading-spinner"></div>
          <p>{{ 'newChatbot.content.loadingContent' | translate }}</p>
        </div>
        } @else {
        <div class="content-accordion">
          @for (courseContent of selectedContent(); track
          courseContent.courseId) {
          <div
            class="accordion-item"
            [class.expanded]="
              expandedCourses().includes(courseContent.courseId)
            "
          >
            <button
              class="accordion-header"
              (click)="toggleCourseExpansion(courseContent.courseId)"
            >
              <div class="header-content">
                <img
                  [src]="
                    expandedCourses().includes(courseContent.courseId)
                      ? '/icons/chevron-down.svg'
                      : '/icons/chevron-up.svg'
                  "
                  alt="Toggle"
                  width="20"
                  height="20"
                />
                <span class="course-name">{{ courseContent.courseName }}</span>
              </div>
              <div class="header-stats">
                <span class="stat">
                  {{ getSelectedCount(courseContent) }}/{{
                    courseContent.items.length
                  }}
                  {{ 'newChatbot.content.itemsSelected' | translate }}
                </span>
                <span class="stat">
                  {{ formatSize(getTotalSize(courseContent)) }}
                </span>
              </div>
            </button>

            @if (expandedCourses().includes(courseContent.courseId)) {
            <div class="accordion-content">
              <div class="content-actions">
                <div class="all">
                  <input
                    class="st2"
                    type="checkbox"
                    [id]="'course-select-' + courseContent.courseId"
                    [checked]="allItemsSelectedInCourse(courseContent.courseId)"
                    (change)="toggleAllInCourse(courseContent.courseId)"
                  />
                  <label [for]="'course-select-' + courseContent.courseId">
                    {{ 'newChatbot.content.selectAll' | translate }}
                  </label>
                </div>
              </div>

              <div class="content-list">
                @for (item of courseContent.items; track item.id) {
                <label class="content-item" [class.selected]="item.selected">
                  <input
                    class="st1"
                    type="checkbox"
                    [checked]="item.selected"
                    (change)="
                      toggleContentItem(courseContent.courseId, item.id)
                    "
                  />
                  <div class="item-icon">
                    <img
                      [src]="
                        '/icons/' +
                        (item.type === 'pdf' ? 'file' : 'file') +
                        '.svg'
                      "
                      [alt]="item.type"
                      width="16"
                      height="16"
                    />
                  </div>
                  <span class="item-name">{{ item.name }}</span>
                  @if (item.size) {
                  <span class="item-size">{{ formatSize(item.size) }}</span>
                  }
                </label>
                }
              </div>
            </div>
            }
          </div>
          }
        </div>

        <div class="selection-summary">
          <div class="summary-stat">
            <span class="stat-label"
              >{{ 'newChatbot.content.totalSelected' | translate }}:</span
            >
            <span class="stat-value">{{ totalSelectedItems() }}</span>
          </div>
          <div class="summary-stat">
            <span class="stat-label"
              >{{ 'newChatbot.content.totalSize' | translate }}:</span
            >
            <span class="stat-value">{{ formatSize(totalSize()) }}</span>
          </div>
        </div>
        }
      </div>
      }
    </div>
  `,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [FormsModule, TranslatePipe],
})
export class ContentSelectionStepComponent implements OnInit {
  private http = inject(HttpClient);

  data = input.required<WizardData>();
  dataChange = output<Partial<WizardData>>();

  isLoadingContent = signal(false);
  selectedContent = signal<SelectedContent[]>([]);
  expandedCourses = signal<string[]>([]);

  contentTypes: ContentType[] = [
    {
      key: 'pdf',
      label: 'newChatbot.content.pdf',
      icon: 'file',
      description: 'PDF files',
    },
    {
      key: 'presentations',
      label: 'newChatbot.content.presentations',
      icon: 'monitor',
      description: 'PowerPoint presentations',
    },
    {
      key: 'web',
      label: 'newChatbot.content.web',
      icon: 'globe',
      description: 'Web content',
    },
    {
      key: 'forums',
      label: 'newChatbot.content.forums',
      icon: 'message-circle',
      description: 'Forum discussions',
    },
    {
      key: 'scorm',
      label: 'newChatbot.content.scorm',
      icon: 'package',
      description: 'SCORM packages',
      isAlpha: true,
    },
    {
      key: 'glossaries',
      label: 'newChatbot.content.glossaries',
      icon: 'book-open',
      description: 'Glossaries',
    },
    {
      key: 'books',
      label: 'newChatbot.content.books',
      icon: 'book',
      description: 'Books',
    },
    {
      key: 'wiki',
      label: 'newChatbot.content.wiki',
      icon: 'edit-3',
      description: 'Wiki pages',
    },
  ];

  hasSelectedTypes = computed(() => {
    const types = this.data().contentTypes;
    return Object.values(types).some((v) => v);
  });

  totalSelectedItems = computed(() => {
    return this.selectedContent().reduce(
      (total, course) =>
        total + course.items.filter((item) => item.selected).length,
      0
    );
  });

  totalSize = computed(() => {
    return this.selectedContent().reduce(
      (total, course) =>
        total +
        course.items
          .filter((item) => item.selected)
          .reduce((sum, item) => sum + (item.size || 0), 0),
      0
    );
  });

  ngOnInit(): void {
    const currentData = this.data();
    if (currentData.selectedContent.length > 0) {
      this.selectedContent.set(currentData.selectedContent);
    } else if (this.hasSelectedTypes()) {
      this.loadContent();
    }
  }

  toggleContentType(type: keyof WizardData['contentTypes']): void {
    const types = { ...this.data().contentTypes };
    types[type] = !types[type];
    this.dataChange.emit({ contentTypes: types });

    if (this.hasSelectedTypes()) {
      this.loadContent();
    }
  }

  async loadContent(): Promise<void> {
    if (this.isLoadingContent()) return;

    this.isLoadingContent.set(true);

    try {
      // TODO: Call API to load content based on selected courses and types
      const content: SelectedContent[] = this.data().selectedCourses.map(
        (courseId) => {
          const course = this.data().courses.find(
            (c) => c.id.toString() === courseId
          );
          return {
            courseId,
            courseName: course?.name || 'Unknown Course',
            items: [],
          };
        }
      );

      this.selectedContent.set(content);
      this.dataChange.emit({ selectedContent: content });
    } catch (error) {
      console.error('Error loading content:', error);
    } finally {
      this.isLoadingContent.set(false);
    }
  }

  toggleCourseExpansion(courseId: string): void {
    const expanded = this.expandedCourses();
    if (expanded.includes(courseId)) {
      this.expandedCourses.set(expanded.filter((id) => id !== courseId));
    } else {
      this.expandedCourses.set([...expanded, courseId]);
    }
  }

  toggleContentItem(courseId: string, itemId: string): void {
    const content = [...this.selectedContent()];
    const course = content.find((c) => c.courseId === courseId);
    if (course) {
      const item = course.items.find((i) => i.id === itemId);
      if (item) {
        item.selected = !item.selected;
        this.selectedContent.set(content);
        this.dataChange.emit({ selectedContent: content });
      }
    }
  }

  selectAllInCourse(courseId: string): void {
    const content = [...this.selectedContent()];
    const course = content.find((c) => c.courseId === courseId);
    if (course) {
      course.items.forEach((item) => (item.selected = true));
      this.selectedContent.set(content);
      this.dataChange.emit({ selectedContent: content });
    }
  }

  deselectAllInCourse(courseId: string): void {
    const content = [...this.selectedContent()];
    const course = content.find((c) => c.courseId === courseId);
    if (course) {
      course.items.forEach((item) => (item.selected = false));
      this.selectedContent.set(content);
      this.dataChange.emit({ selectedContent: content });
    }
  }

  getSelectedCount(courseContent: SelectedContent): number {
    return courseContent.items.filter((item) => item.selected).length;
  }

  getTotalSize(courseContent: SelectedContent): number {
    return courseContent.items
      .filter((item) => item.selected)
      .reduce((sum, item) => sum + (item.size || 0), 0);
  }

  formatSize(bytes: number): string {
    if (bytes === 0) return '0 Bytes';
    const k = 1024;
    const sizes = ['Bytes', 'KB', 'MB', 'GB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return Math.round((bytes / Math.pow(k, i)) * 100) / 100 + ' ' + sizes[i];
  }

  allItemsSelectedInCourse(courseId: string): boolean {
    const course = this.selectedContent().find((c) => c.courseId === courseId);
    if (!course || course.items.length === 0) return false;
    return course.items.every((item) => item.selected);
  }

  toggleAllInCourse(courseId: string): void {
    const content = [...this.selectedContent()];
    const course = content.find((c) => c.courseId === courseId);

    if (course) {
      const allSelected = course.items.every((item) => item.selected);
      course.items.forEach((item) => (item.selected = !allSelected));
      this.selectedContent.set(content);
      this.dataChange.emit({ selectedContent: content });
    }
  }
}
