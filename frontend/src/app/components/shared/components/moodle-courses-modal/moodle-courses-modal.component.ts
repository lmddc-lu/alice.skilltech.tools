import {
  Component,
  ChangeDetectionStrategy,
  signal,
  computed,
  input,
  output,
  inject,
  effect,
} from '@angular/core';

import { FormsModule } from '@angular/forms';
import {
  MoodleCoursesService,
  UpdateCoursesResponse,
} from '../../../../services/courses/moodle-courses.service';
import {
  MoodleCoursesData,
  MoodleCourseInfo,
} from '../../../../interfaces/chatbot-i';
import { TranslatePipe } from '@ngx-translate/core';
import { MlangPipe } from '../../../../core/mlang.pipe';

@Component({
  selector: 'app-moodle-courses-modal',
  imports: [FormsModule, TranslatePipe, MlangPipe],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <div class="moodle-courses-modal">
      <div
        class="modal-overlay"
        role="dialog"
        aria-modal="true"
        aria-labelledby="modal-title"
        (click)="onOverlayClick($event)"
      >
        <div class="modal-container" (click)="$event.stopPropagation()">
          <div class="modal-header">
            <h2 id="modal-title">{{ 'moodleModal.title' | translate }}</h2>
            <button
              type="button"
              class="close-button"
              aria-label="Close modal"
              (click)="close.emit()"
            >
              <svg
                width="24"
                height="24"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                stroke-width="2"
                aria-hidden="true"
              >
                <path d="M18 6L6 18M6 6l12 12" />
              </svg>
            </button>
          </div>

          @if (loading()) {
          <div
            class="modal-body loading-state"
            role="status"
            aria-live="polite"
          >
            <div class="spinner" aria-hidden="true"></div>
            <p>{{ 'moodleModal.loadingCourses' | translate }}</p>
          </div>
          }

          @if (error()) {
          <div class="modal-body error-state" role="alert">
            <p class="error-message">{{ error() }}</p>
            <button type="button" class="retry-button" (click)="loadCourses()">
              {{ 'moodleModal.retry' | translate }}
            </button>
          </div>
          }

          @if (!loading() && !error() && data()) {
          <div class="modal-body">
            <div class="toolbar">
              <div class="toolbar-left">
                <button
                  type="button"
                  class="toolbar-button"
                  (click)="loadCourses()"
                  [disabled]="loading()"
                  aria-label="Refresh courses"
                >
                  <img
                    src="/icons/refresh2.svg"
                    alt="Refresh"
                    width="16"
                    height="16"
                  />

                  <span>{{ 'moodleModal.refresh' | translate }}</span>
                </button>
                <div class="all">
                  <input
                    class="st2"
                    type="checkbox"
                    id="scales"
                    name="scales"
                    [checked]="allSelected()"
                    (change)="toggleSelectAll()"
                  />
                  {{ 'moodleModal.selectAll' | translate }}
                </div>
              </div>

              <div class="toolbar-right">
                <span class="selection-count" role="status" aria-live="polite">
                  {{ selectedCourses().size }}
                  {{ 'moodleModal.of' | translate }} {{ allCourses().length }}
                  {{ 'moodleModal.selected' | translate }}
                </span>
              </div>
            </div>

            <div class="search-container">
              <div class="search-input-wrapper">
                <svg
                  class="search-icon"
                  width="20"
                  height="20"
                  viewBox="0 0 24 24"
                  fill="none"
                  stroke="currentColor"
                  stroke-width="2"
                  aria-hidden="true"
                >
                  <circle cx="11" cy="11" r="8" />
                  <path d="m21 21-4.35-4.35" />
                </svg>
                <input
                  id="course-search"
                  type="search"
                  class="search-input"
                  placeholder="Search courses..."
                  [value]="searchQuery()"
                  (input)="searchQuery.set($any($event.target).value)"
                  aria-label="Search courses"
                />
              </div>
            </div>

            <div class="courses-grid">
              @if (filteredCourses().length === 0) {
              <div class="empty-state">
                <svg
                  width="48"
                  height="48"
                  viewBox="0 0 24 24"
                  fill="none"
                  stroke="currentColor"
                  stroke-width="2"
                  aria-hidden="true"
                >
                  <path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20" />
                  <path
                    d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z"
                  />
                </svg>
                <p class="empty-title">
                  {{ 'moodleModal.noCoursesFound' | translate }}
                </p>
                <p class="empty-description">
                  {{ 'moodleModal.adjustSearch' | translate }}
                </p>
              </div>
              } @else { @for (course of filteredCourses(); track
              course.selection_key) {
              <label class="course-card">
                <input
                  type="checkbox"
                  class="course-checkbox"
                  [checked]="selectedCourses().has(course.selection_key)"
                  (change)="toggleCourse(course.selection_key)"
                  [attr.aria-label]="'Select ' + course.course_name"
                />
                <div class="course-content">
                  <div class="course-header">
                    <h3 class="course-name">{{ course.course_name | mlang }}</h3>
                  </div>

                  @if (course.description) {
                  <p class="course-description" [innerHTML]="course.description | mlang"></p>
                  }

                  <div class="course-tags">
                    <span class="course-category">{{ course.category | mlang }}</span>
                  </div>
                </div>
              </label>
              } }
            </div>
          </div>

          <div class="modal-footer">
            <button
              type="button"
              class="button button-secondary"
              (click)="close.emit()"
            >
              {{ 'moodleModal.cancel' | translate }}
            </button>
            <button
              type="button"
              class="button button-primary"
              [disabled]="saving() || !hasChanges()"
              (click)="saveChanges()"
            >
              @if (saving()) {
              <span class="button-spinner" aria-hidden="true"></span>
              <span>{{ 'moodleModal.saving' | translate }}</span>
              } @else {
              <span>{{ 'moodleModal.saveChanges' | translate }}</span>
              <img
                src="/icons/icon_check.svg"
                alt="Create"
                width="16"
                height="16"
              />
              }
            </button>
          </div>
          }
        </div>
      </div>
    </div>
  `,
  styles: [],
})
export class MoodleCoursesModalComponent {
  private moodleService = inject(MoodleCoursesService);

  chatbotId = input.required<string>();
  isOpen = input<boolean>(false);

  close = output<void>();
  saved = output<void>();

  loading = signal(false);
  saving = signal(false);
  error = signal<string | null>(null);
  data = signal<MoodleCoursesData | null>(null);
  selectedCourses = signal<Set<string>>(new Set());
  initialSelection = signal<Set<string>>(new Set());
  searchQuery = signal('');

  allCourses = computed(() => {
    const currentData = this.data();
    if (!currentData) return [];

    return [...currentData.linked_courses, ...currentData.available_courses];
  });

  filteredCourses = computed(() => {
    const courses = this.allCourses();
    const query = this.searchQuery().toLowerCase().trim();

    if (!query) return courses;

    return courses.filter(
      (course) =>
        course.course_name.toLowerCase().includes(query) ||
        course.description?.toLowerCase().includes(query) ||
        course.category.toLowerCase().includes(query) ||
        course.datasource_name.toLowerCase().includes(query)
    );
  });

  allSelected = computed(() => {
    const filtered = this.filteredCourses();
    const selected = this.selectedCourses();

    if (filtered.length === 0) return false;

    return filtered.every((course) => selected.has(course.selection_key));
  });

  hasChanges = computed(() => {
    const initial = this.initialSelection();
    const current = this.selectedCourses();

    if (initial.size !== current.size) return true;

    for (const key of current) {
      if (!initial.has(key)) return true;
    }

    return false;
  });

  constructor() {
    effect(() => {
      if (this.isOpen()) {
        this.loadCourses();
      }
    });
  }

  loadCourses(): void {
    this.loading.set(true);
    this.error.set(null);

    this.moodleService.getMoodleCourses(this.chatbotId()).subscribe({
      next: (response) => {
        this.data.set(response);
        const linked = new Set(
          response.linked_courses.map((c) => c.selection_key)
        );
        this.selectedCourses.set(new Set(linked));
        this.initialSelection.set(new Set(linked));
        this.loading.set(false);
      },
      error: (err) => {
        this.error.set(
          err.error?.message || 'Failed to load courses. Please try again.'
        );
        this.loading.set(false);
      },
    });
  }

  toggleCourse(selectionKey: string): void {
    this.selectedCourses.update((selected) => {
      const newSet = new Set(selected);
      if (newSet.has(selectionKey)) {
        newSet.delete(selectionKey);
      } else {
        newSet.add(selectionKey);
      }
      return newSet;
    });
  }

  toggleSelectAll(): void {
    const filtered = this.filteredCourses();
    const allCurrentlySelected = this.allSelected();

    this.selectedCourses.update((selected) => {
      const newSet = new Set(selected);

      if (allCurrentlySelected) {
        filtered.forEach((course) => {
          newSet.delete(course.selection_key);
        });
      } else {
        filtered.forEach((course) => {
          newSet.add(course.selection_key);
        });
      }

      return newSet;
    });
  }

  isLinkedCourse(selectionKey: string): boolean {
    return this.initialSelection().has(selectionKey);
  }

  saveChanges(): void {
    const currentData = this.data();
    if (!currentData || this.saving()) return;

    this.saving.set(true);
    this.error.set(null);

    const selectionKeys = Array.from(this.selectedCourses());

    this.moodleService
      .updateCourseSelection(currentData.chatbot_id, selectionKeys)
      .subscribe({
        next: (response: UpdateCoursesResponse) => {
          this.saving.set(false);
          this.initialSelection.set(new Set(this.selectedCourses()));

          console.log('Course update response:', {
            added: response.total_added,
            removed: response.total_removed,
            total: response.total_courses,
            reindexing: response.reindexing,
            reindex_error: response.reindex_error,
          });

          this.saved.emit();
          this.close.emit();
        },
        error: (err) => {
          this.error.set(
            err.error?.message || 'Failed to save changes. Please try again.'
          );
          this.saving.set(false);
        },
      });
  }

  onOverlayClick(event: MouseEvent): void {
    if (event.target === event.currentTarget) {
      this.close.emit();
    }
  }

  stripHtml(html: string): string {
    if (!html) return '';
    const div = document.createElement('div');
    div.innerHTML = html;
    return div.textContent || div.innerText || '';
  }
}
