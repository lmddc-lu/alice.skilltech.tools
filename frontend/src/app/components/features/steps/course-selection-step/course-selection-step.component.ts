import {
  Component,
  input,
  output,
  signal,
  computed,
  inject,
  OnInit,
  ChangeDetectionStrategy,
} from '@angular/core';

import { FormsModule } from '@angular/forms';
import { TranslatePipe } from '@ngx-translate/core';
import { HttpClient, HttpParams } from '@angular/common/http';
import {
  MoodleCourse,
  WizardData,
} from '../../new-chatbot/new-chatbot.component';
import { environment } from '../../../../../environments/environment';
import { firstValueFrom } from 'rxjs';

interface MoodleCoursesResponse {
  courses: {
    course_id: number;
    fullname: string;
    shortname: string;
    description: string;
    category: string;
    course_url: string;
  }[];
  total_courses: number;
  returned_courses: number;
  has_more: boolean;
}

@Component({
  selector: 'app-course-selection-step',
  template: `
  <div class="step-container course-selection">
  <div class="actions-bar">
  <button
  class="btn btn-secondary"
  (click)="refreshCourses()"
  [disabled]="isLoadingCourses()"
  >
  @if (isLoadingCourses()) {
    <div class="loading-spinner small"></div>
  } @else {
    <img src="/icons/refresh2.svg" alt="Refresh" width="16" height="16" />
  }
  {{ 'newChatbot.courseSelection.refreshCourses' | translate }}
  </button>
  
  <div class="search-box">
  <img src="/icons/search.svg" alt="Search" width="16" height="16" />
  <input
  type="text"
  class="form-control"
  [(ngModel)]="searchTerm"
  [placeholder]="
  'newChatbot.courseSelection.searchPlaceholder' | translate
  "
  />
  </div>
  </div>
  
  <div class="selection-controls">
  <div class="selection-info">
  <span
  >{{ selectedCount() }}
  {{ 'newChatbot.courseSelection.coursesSelected' | translate }}</span
  >
  </div>
  <div class="selection-actions">
  <div class="all">
  <input
  class="st2"
  type="checkbox"
  id="scales"
  name="scales"
  [checked]="allSelected()"
  (change)="toggleSelectAll()"
  />
  <label for="scales">{{
    'newChatbot.courseSelection.selectAll' | translate
  }}</label>
  </div>
  </div>
  </div>

  @if (isLoadingCourses() && courses().length === 0) {
    <div class="loading-state">
    <div class="loading-spinner"></div>
    <p>{{ 'newChatbot.courseSelection.loadingCourses' | translate }}</p>
    </div>
  } @else if (courses().length === 0) {
    <div class="empty-state">
    <img src="/icons/package.svg" alt="No courses" width="48" height="48" />
    <p>{{ 'newChatbot.courseSelection.noCourses' | translate }}</p>
    <button class="btn btn-primary" (click)="refreshCourses()">
    {{ 'newChatbot.courseSelection.loadCourses' | translate }}
    </button>
    </div>
  } @else {
    <div class="courses-grid">
    @for (course of filteredCourses(); track course.id) {
      <div
      class="course-card"
      [class.selected]="isSelected(course.id)"
      (click)="toggleCourse(course.id)"
      >
      <div class="course-checkbox">
      <input
      type="checkbox"
      class="st1"
      [checked]="isSelected(course.id)"
      (click)="$event.stopPropagation()"
      (change)="toggleCourse(course.id)"
      />
      </div>
      <div class="course-content">
      <div class="course-icon">
      </div>
      <div class="row">
          <img
          src="/icons/icon_book.svg"
          alt="Course"
          width="24"
          height="24"
          />
        <div class="title">
        <h4 class="course-name">{{ course.name }}</h4>
        <p class="course-shortname">{{ course.shortname }}</p>
        </div>
      </div>


      @if (course.description) {
        <p class="course-description" [innerHTML]="course.description"></p>
      }
      <span class="course-category">{{ course.category }}</span>
      </div>
      </div>
    }
    </div>

    @if (totalPages() > 1) {
      <div class="pagination-controls">
        <button
          class="btn btn-pagination"
          (click)="previousPage()"
          [disabled]="currentPage() === 1 || isLoadingCourses()"
        >
          <img src="/icons/chevron-left.svg" alt="Previous" width="16" height="16" />
          {{ 'newChatbot.courseSelection.previous' | translate }}
        </button>

        <div class="pagination-info">
          <span class="page-indicator">
            {{ currentPage() }} / {{ totalPages() }}
          </span>
          <span class="total-courses">
            ({{ totalCoursesCount() }} {{ 'newChatbot.courseSelection.totalCourses' | translate }})
          </span>
        </div>

        <button
          class="btn btn-pagination"
          (click)="nextPage()"
          [disabled]="currentPage() === totalPages() || isLoadingCourses()"
        >
          {{ 'newChatbot.courseSelection.next' | translate }}
          <img src="/icons/chevron-left.svg" alt="Next" width="16" height="16" class="rotate-180" />
        </button>
      </div>
    }
  }

  @if (categories().length > 1) {
    <div class="category-filter">
    <label class="filter-label">{{
      'newChatbot.courseSelection.filterByCategory' | translate
    }}</label>
    <div class="category-tags">
    <button
    class="category-tag"
    [class.active]="!selectedCategory()"
    (click)="selectedCategory.set('')"
    >
    {{ 'newChatbot.courseSelection.allCategories' | translate }}
    </button>
    @for (category of categories(); track category) {
      <button
      class="category-tag"
      [class.active]="selectedCategory() === category"
      (click)="selectedCategory.set(category)"
      >
      {{ category }}
      </button>
    }
    </div>
    </div>
  }
  </div>
  `,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [FormsModule, TranslatePipe],
})
export class CourseSelectionStepComponent implements OnInit {
  private http = inject(HttpClient);
  
  data = input.required<WizardData>();
  dataChange = output<Partial<WizardData>>();
  
  courses = signal<MoodleCourse[]>([]);
  selectedCourses = signal<number[]>([]);
  isLoadingCourses = signal(false);
  searchTerm = signal('');
  selectedCategory = signal('');

  currentPage = signal(1);
  totalCoursesCount = signal(0);
  hasMoreCourses = signal(false);
  readonly pageSize = 6;

  totalPages = computed(() => Math.ceil(this.totalCoursesCount() / this.pageSize));
  currentOffset = computed(() => (this.currentPage() - 1) * this.pageSize);

  filteredCourses = computed(() => {
    let filtered = this.courses();
    const search = this.searchTerm().toLowerCase();
    const category = this.selectedCategory();
    
    if (search) {
      filtered = filtered.filter(
        (course) =>
          course.name.toLowerCase().includes(search) ||
        course.shortname.toLowerCase().includes(search)
      );
    }
    
    if (category) {
      filtered = filtered.filter((course) => course.category === category);
    }
    
    return filtered;
  });
  
  categories = computed(() => {
    const cats = new Set(this.courses().map((c) => c.category));
    return Array.from(cats).sort();
  });
  
  selectedCount = computed(() => this.selectedCourses().length);
  
  allSelected = computed(() => {
    const filtered = this.filteredCourses();
    return (
      filtered.length > 0 &&
      filtered.every((course) => this.selectedCourses().includes(course.id))
    );
  });
  
  ngOnInit(): void {
    const currentData = this.data();
    if (currentData.courses.length > 0) {
      this.courses.set(currentData.courses);
      const selectedIds = currentData.selectedCourses.map((id) =>
        typeof id === 'string' ? parseInt(id) : id
    );
    this.selectedCourses.set(selectedIds);
  } else {
    this.refreshCourses();
  }
}

async loadPage(page: number): Promise<void> {
  if (this.isLoadingCourses()) return;
  if (page < 1 || (this.totalPages() > 0 && page > this.totalPages())) return;

  this.isLoadingCourses.set(true);
  this.currentPage.set(page);
  const offset = (page - 1) * this.pageSize;

  try {
    const currentData = this.data();
    if (!currentData.moodleUrl || !currentData.moodleToken) {
      console.error('Moodle URL and token are required');
      return;
    }

    const params = new HttpParams()
      .set('limit', this.pageSize.toString())
      .set('offset', offset.toString());

    const response = await firstValueFrom(
      this.http.post<MoodleCoursesResponse>(
        `${environment.apiBaseUrl}/moodle/list-courses`,
        {
          moodle_url: currentData.moodleUrl,
          token: currentData.moodleToken,
        },
        {
          params,
        }
      )
    );

    if (response) {
      const mappedCourses: MoodleCourse[] = response.courses.map(
        (course) => ({
          id: course.course_id,
          fullname: course.fullname,
          name: course.fullname,
          shortname: course.shortname,
          category: course.category,
          description: course.description,
          course_url: course.course_url,
        })
      );

      this.courses.set(mappedCourses);
      this.totalCoursesCount.set(response.total_courses);
      this.hasMoreCourses.set(response.has_more);

      this.dataChange.emit({ courses: mappedCourses });
    }
  } catch (error: any) {
    console.error('Error loading courses:', error);

    let errorMessage = 'Failed to load courses. Please try again.';
    if (error?.error?.error) {
      errorMessage = error.error.error;
    }

    alert(errorMessage);
  } finally {
    this.isLoadingCourses.set(false);
  }
}

async refreshCourses(): Promise<void> {
  this.currentPage.set(1);
  await this.loadPage(1);
}

goToPage(page: number): void {
  this.loadPage(page);
}

nextPage(): void {
  if (this.currentPage() < this.totalPages()) {
    this.loadPage(this.currentPage() + 1);
  }
}

previousPage(): void {
  if (this.currentPage() > 1) {
    this.loadPage(this.currentPage() - 1);
  }
}
  
  toggleCourse(courseId: number): void {
    const current = this.selectedCourses();
    const updated = current.includes(courseId)
    ? current.filter((id) => id !== courseId)
    : [...current, courseId];
    
    this.selectedCourses.set(updated);
    this.dataChange.emit({
      selectedCourses: updated.map((id) => id.toString()),
    });
  }
  
  isSelected(courseId: number): boolean {
    return this.selectedCourses().includes(courseId);
  }
  
  toggleSelectAll(): void {
    const allIds = this.filteredCourses().map((c) => c.id);
    const current = this.selectedCourses();
    
    const allCurrentlySelected = allIds.every((id) => current.includes(id));
    
    let updated: number[];
    if (allCurrentlySelected) {
      updated = current.filter((id) => !allIds.includes(id));
    } else {
      updated = Array.from(new Set([...current, ...allIds]));
    }
    
    this.selectedCourses.set(updated);
    this.dataChange.emit({
      selectedCourses: updated.map((id) => id.toString()),
    });
  }
  
  selectAll(): void {
    const allIds = this.filteredCourses().map((c) => c.id);
    const current = this.selectedCourses();
    const updated = Array.from(new Set([...current, ...allIds]));
    
    this.selectedCourses.set(updated);
    this.dataChange.emit({
      selectedCourses: updated.map((id) => id.toString()),
    });
  }
  
  deselectAll(): void {
    const filterIds = this.filteredCourses().map((c) => c.id);
    const updated = this.selectedCourses().filter(
      (id) => !filterIds.includes(id)
    );
    
    this.selectedCourses.set(updated);
    this.dataChange.emit({
      selectedCourses: updated.map((id) => id.toString()),
    });
  }
}
