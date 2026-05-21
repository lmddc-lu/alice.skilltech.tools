import {
  Component,
  signal,
  computed,
  inject,
  OnInit,
  ChangeDetectionStrategy,
} from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { RouterLink } from '@angular/router';
import { TranslatePipe } from '@ngx-translate/core';
import { AdminService, Job } from '../../../../services/admin/admin.service';

@Component({
  selector: 'app-admin-jobs',
  imports: [CommonModule, FormsModule, RouterLink, TranslatePipe],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <div class="admin-jobs">
      <div class="jobs-header">
        <h1>{{ 'admin.jobs.title' | translate }}</h1>

        <button class="btn btn-ghost" [routerLink]="['/admin']">
          <img src="/icons/arrow-left.svg" alt="Back" width="20" height="20" />
          {{ 'admin.jobs.backToDashboard' | translate }}
        </button>
        <button class="btn btn-secondary" (click)="refresh()">
          <img src="/icons/refresh.svg" alt="Refresh" width="16" height="16" />
          {{ 'admin.jobs.refresh' | translate }}
        </button>
      </div>

      <div class="filters-section">
        <div class="filter-group">
          <label>{{ 'admin.jobs.jobType' | translate }}</label>
          <select [(ngModel)]="filterJobType" (change)="applyFilters()">
            <option value="">{{ 'admin.jobs.allTypes' | translate }}</option>
            <option value="ingestion">Ingestion</option>
            <option value="metadata_sync">Metadata Sync</option>
            <option value="content_sync">Content Sync</option>
          </select>
        </div>

        <div class="filter-group">
          <label>{{ 'admin.jobs.status' | translate }}</label>
          <select [(ngModel)]="filterStatus" (change)="applyFilters()">
            <option value="">{{ 'admin.jobs.allStatuses' | translate }}</option>
            <option value="pending">Pending</option>
            <option value="running">Running</option>
            <option value="completed">Completed</option>
            <option value="failed">Failed</option>
            <option value="cancelled">Cancelled</option>
          </select>
        </div>

        <div class="filter-group">
          <label>{{ 'admin.jobs.limit' | translate }}</label>
          <select [(ngModel)]="filterLimit" (change)="applyFilters()">
            <option value="25">25</option>
            <option value="50">50</option>
            <option value="100">100</option>
          </select>
        </div>
      </div>

      @if (loading()) {
      <div class="loading-container">
        <div class="loading-spinner"></div>
        <p>{{ 'admin.jobs.loading' | translate }}</p>
      </div>
      } @else if (error()) {
      <div class="error-container">
        <p>{{ error() }}</p>
        <button class="btn btn-primary" (click)="refresh()">
          {{ 'admin.jobs.retry' | translate }}
        </button>
      </div>
      } @else if (jobs().length === 0) {
      <div class="empty-state">
        <img src="/icons/package.svg" alt="No jobs" width="48" height="48" />
        <p>{{ 'admin.jobs.noJobs' | translate }}</p>
      </div>
      } @else {
      <div class="jobs-table">
        <table>
          <thead>
            <tr>
              <th>{{ 'admin.jobs.type' | translate }}</th>
              <th>{{ 'admin.jobs.status' | translate }}</th>
              <th>{{ 'admin.jobs.created' | translate }}</th>
              <th>{{ 'admin.jobs.duration' | translate }}</th>
              <th>{{ 'admin.jobs.progress' | translate }}</th>
              <th>{{ 'admin.jobs.actions' | translate }}</th>
            </tr>
          </thead>
          <tbody>
            @for (job of jobs(); track job.id) {
            <tr>
              <td>
                <div class="job-type-cell">
                  <img
                    [src]="getJobTypeIcon(job.job_type)"
                    alt="Job"
                    width="20"
                    height="20"
                  />
                  <div class="job-info">
                    <span class="job-type">{{ job.job_type }}</span>
                    <span class="job-id">{{ job.id.slice(0, 8) }}...</span>
                  </div>
                </div>
              </td>
              <td>
                <span class="status-badge" [class]="'status-' + job.status">
                  {{ job.status }}
                </span>
              </td>
              <td>{{ job.created_at | date : 'short' }}</td>
              <td>{{ formatDuration(job.duration_seconds) }}</td>
              <td>
                @if (job.progress) {
                <div class="progress-cell">
                  <div class="progress-bar">
                    <div
                      class="progress-fill"
                      [style.width.%]="job.progress.percentage"
                    ></div>
                  </div>
                  <span class="progress-text"
                    >{{ job.progress.percentage }}%</span
                  >
                </div>
                } @else {
                <span>-</span>
                }
              </td>
              <td>
                <div class="actions-cell">
                  <button
                    class="btn-icon"
                    [routerLink]="['/admin/jobs', job.id]"
                    title="View details"
                  >
                    <img
                      src="/icons/eye.svg"
                      alt="View"
                      width="16"
                      height="16"
                    />
                  </button>
                  @if (job.status === 'running' || job.status === 'pending') {
                  <button
                    class="btn-icon"
                    (click)="cancelJob(job.id)"
                    title="Cancel"
                  >
                    <img
                      src="/icons/x-circle.svg"
                      alt="Cancel"
                      width="16"
                      height="16"
                    />
                  </button>
                  } @if (job.status === 'failed') {
                  <button
                    class="btn-icon"
                    (click)="retryJob(job.id)"
                    title="Retry"
                  >
                    <img
                      src="/icons/refresh.svg"
                      alt="Retry"
                      width="16"
                      height="16"
                    />
                  </button>
                  }
                </div>
              </td>
            </tr>
            }
          </tbody>
        </table>
      </div>
      }
    </div>
  `,
  styles: `
    .admin-jobs {
      padding: 2rem;
      max-width: 1400px;
      margin: 0 auto;
      background-color: aliceblue;
    }

    .jobs-header {
      display: flex;
      justify-content: space-between;
      align-items: center;
      margin-bottom: 2rem;

      h1 {
        margin: 0;
        font-size: 2rem;
        font-weight: 700;
      }
    }

    .filters-section {
      display: flex;
      gap: 1rem;
      margin-bottom: 2rem;
      padding: 1.5rem;
      background: white;
      border-radius: 12px;
      border: 1px solid #e2e8f0;

      .filter-group {
        display: flex;
        flex-direction: column;
        gap: 0.5rem;
        flex: 1;

        label {
          font-size: 0.875rem;
          font-weight: 600;
          color: #475569;
        }

        select {
          padding: 0.5rem;
          border: 1px solid #e2e8f0;
          border-radius: 6px;
          font-size: 0.875rem;

          &:focus {
            outline: none;
            border-color: #3b82f6;
          }
        }
      }
    }

    .jobs-table {
      background: white;
      border-radius: 12px;
      border: 1px solid #e2e8f0;
      overflow: hidden;

      table {
        width: 100%;
        border-collapse: collapse;

        thead {
          background: #f8fafc;
          border-bottom: 1px solid #e2e8f0;

          th {
            padding: 1rem;
            text-align: left;
            font-size: 0.875rem;
            font-weight: 600;
            color: #475569;
          }
        }

        tbody {
          tr {
            border-bottom: 1px solid #e2e8f0;

            &:hover {
              background: #f8fafc;
            }

            &:last-child {
              border-bottom: none;
            }

            td {
              padding: 1rem;
              font-size: 0.875rem;
            }
          }
        }
      }
    }

    .job-type-cell {
      display: flex;
      align-items: center;
      gap: 0.75rem;

      .job-info {
        display: flex;
        flex-direction: column;
        gap: 0.25rem;

        .job-type {
          font-weight: 600;
        }

        .job-id {
          color: #64748b;
          font-size: 0.75rem;
        }
      }
    }

    .status-badge {
      padding: 0.375rem 0.75rem;
      border-radius: 6px;
      font-size: 0.75rem;
      font-weight: 600;
      text-transform: uppercase;

      &.status-pending {
        background: #f3f4f6;
        color: #374151;
      }

      &.status-running {
        background: #fef3c7;
        color: #92400e;
      }

      &.status-completed {
        background: #d1fae5;
        color: #065f46;
      }

      &.status-failed {
        background: #fee2e2;
        color: #991b1b;
      }

      &.status-cancelled {
        background: #e5e7eb;
        color: #4b5563;
      }
    }

    .progress-cell {
      display: flex;
      align-items: center;
      gap: 0.5rem;

      .progress-bar {
        flex: 1;
        height: 8px;
        background: #e2e8f0;
        border-radius: 4px;
        overflow: hidden;

        .progress-fill {
          height: 100%;
          background: #3b82f6;
          transition: width 0.3s;
        }
      }

      .progress-text {
        font-size: 0.75rem;
        font-weight: 600;
      }
    }

    .actions-cell {
      display: flex;
      gap: 0.5rem;
    }

    .btn-icon {
      padding: 0.375rem;
      background: transparent;
      border: 1px solid #e2e8f0;
      border-radius: 6px;
      cursor: pointer;
      transition: all 0.2s;

      &:hover {
        background: #f8fafc;
        border-color: #cbd5e1;
      }
    }

    .loading-container,
    .error-container,
    .empty-state {
      display: flex;
      flex-direction: column;
      align-items: center;
      justify-content: center;
      padding: 4rem 2rem;
      gap: 1rem;
    }
  `,
})
export class AdminJobsComponent implements OnInit {
  private adminService = inject(AdminService);

  loading = signal(false);
  error = signal<string | null>(null);
  jobs = signal<Job[]>([]);

  filterJobType = signal('');
  filterStatus = signal('');
  filterLimit = signal(50);

  ngOnInit(): void {
    this.loadJobs();
  }

  loadJobs(): void {
    this.loading.set(true);
    this.error.set(null);

    const filters: any = {
      limit: this.filterLimit(),
    };

    if (this.filterJobType()) {
      filters.job_type = this.filterJobType();
    }

    if (this.filterStatus()) {
      filters.status = this.filterStatus();
    }

    this.adminService.getJobs(filters).subscribe({
      next: (jobs) => {
        this.jobs.set(jobs);
        this.loading.set(false);
      },
      error: (err) => {
        console.error('Error loading jobs:', err);
        this.error.set('Failed to load jobs');
        this.loading.set(false);
      },
    });
  }

  applyFilters(): void {
    this.loadJobs();
  }

  refresh(): void {
    this.loadJobs();
  }

  cancelJob(jobId: string): void {
    if (!confirm('Are you sure you want to cancel this job?')) return;

    this.adminService.cancelJob(jobId).subscribe({
      next: () => {
        this.loadJobs();
      },
      error: (err) => {
        console.error('Error cancelling job:', err);
        alert('Failed to cancel job');
      },
    });
  }

  retryJob(jobId: string): void {
    this.adminService.retryJob(jobId).subscribe({
      next: () => {
        this.loadJobs();
      },
      error: (err) => {
        console.error('Error retrying job:', err);
        alert('Failed to retry job');
      },
    });
  }

  getJobTypeIcon(jobType: string): string {
    switch (jobType) {
      case 'ingestion':
        return '/icons/upload.svg';
      case 'metadata_sync':
        return '/icons/refresh.svg';
      case 'content_sync':
        return '/icons/download.svg';
      default:
        return '/icons/package.svg';
    }
  }

  formatDuration(seconds: number | null): string {
    if (!seconds) return '-';
    if (seconds < 60) return `${Math.round(seconds)}s`;
    const minutes = Math.floor(seconds / 60);
    const remainingSeconds = Math.round(seconds % 60);
    return `${minutes}m ${remainingSeconds}s`;
  }
}
