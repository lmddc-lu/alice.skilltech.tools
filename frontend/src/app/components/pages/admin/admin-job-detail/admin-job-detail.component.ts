import {
  Component,
  signal,
  computed,
  inject,
  OnInit,
  OnDestroy,
  ChangeDetectionStrategy,
} from '@angular/core';
import { CommonModule } from '@angular/common';
import { ActivatedRoute, Router, RouterLink } from '@angular/router';
import { TranslatePipe } from '@ngx-translate/core';
import {
  AdminService,
  JobDetail,
  JobFile,
} from '../../../../services/admin/admin.service';

@Component({
  selector: 'app-admin-job-detail',
  imports: [CommonModule, RouterLink, TranslatePipe],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <div class="job-detail">
      <div class="detail-header">
        <button class="btn btn-ghost" [routerLink]="['/admin/jobs']">
          <img src="/icons/arrow-left.svg" alt="Back" width="20" height="20" />
          {{ 'admin.jobDetail.backToJobs' | translate }}
        </button>
      </div>

      @if (loading()) {
      <div class="loading-container">
        <div class="loading-spinner"></div>
        <p>{{ 'admin.jobDetail.loading' | translate }}</p>
      </div>
      } @else if (error()) {
      <div class="error-container">
        <p>{{ error() }}</p>
        <button class="btn btn-primary" (click)="loadJob()">
          {{ 'admin.jobDetail.retry' | translate }}
        </button>
      </div>
      } @else if (job()) {
      <div class="detail-content">
        <div class="detail-card overview-card">
          <div class="card-header">
            <div class="job-title">
              <img
                [src]="getJobTypeIcon(job()!.job_type)"
                alt="Job"
                width="32"
                height="32"
              />
              <div>
                <h1>{{ job()!.job_type }}</h1>
                <span class="job-id">{{ job()!.id }}</span>
              </div>
            </div>
            <span class="status-badge" [class]="'status-' + job()!.status">
              {{ job()!.status }}
            </span>
          </div>

          @if (job()!.progress) {
          <div class="progress-section">
            <div class="progress-header">
              <span class="progress-label">{{ job()!.progress!.message }}</span>
              <div class="progress-header-right">
                <span class="progress-percentage"
                  >{{ job()!.progress!.percentage }}%</span
                >
                @if (hasFiles()) {
                <button
                  type="button"
                  class="btn-toggle-files"
                  (click)="toggleFilesExpanded()"
                  [attr.aria-expanded]="filesExpanded()"
                  [attr.aria-label]="
                    (filesExpanded()
                      ? 'admin.jobDetail.hideFiles'
                      : 'admin.jobDetail.showFiles'
                    ) | translate
                  "
                >
                  <span class="file-count">
                    {{ job()!.files.length }}
                    {{ 'admin.jobDetail.files' | translate }}
                  </span>
                  <span
                    class="chevron"
                    [class.chevron-open]="filesExpanded()"
                    aria-hidden="true"
                    >▾</span
                  >
                </button>
                }
              </div>
            </div>
            <div class="progress-bar">
              <div
                class="progress-fill"
                [style.width.%]="job()!.progress!.percentage"
              ></div>
            </div>
            <div class="progress-details">
              <span
                >{{ job()!.progress!.current }} /
                {{ job()!.progress!.total }}</span
              >
            </div>

            @if (filesExpanded() && hasFiles()) {
            <div class="file-list" role="region" aria-label="File progress">
              @for (file of job()!.files; track file.id) {
              <div class="file-row">
                <div class="file-row-main">
                  <span class="file-name" [title]="file.filename">{{
                    file.filename
                  }}</span>
                  <span
                    class="file-state-badge"
                    [class]="'file-state-' + file.state"
                    >{{ 'fileState.' + file.state | translate }}</span
                  >
                </div>
                @if (file.error_message) {
                <div class="file-error" [title]="file.error_message">
                  {{ file.error_message }}
                </div>
                } @if (file.error_detail) {
                <details class="file-error-detail">
                  <summary>
                    {{ 'admin.jobDetail.showErrorDetail' | translate }}
                  </summary>
                  <pre>{{ file.error_detail }}</pre>
                </details>
                }
              </div>
              }
            </div>
            }
          </div>
          }

          <div class="timestamps-grid">
            <div class="timestamp-item">
              <span class="timestamp-label">{{
                'admin.jobDetail.created' | translate
              }}</span>
              <span class="timestamp-value">{{
                job()!.created_at | date : 'medium'
              }}</span>
            </div>
            @if (job()!.started_at) {
            <div class="timestamp-item">
              <span class="timestamp-label">{{
                'admin.jobDetail.started' | translate
              }}</span>
              <span class="timestamp-value">{{
                job()!.started_at | date : 'medium'
              }}</span>
            </div>
            } @if (job()!.completed_at) {
            <div class="timestamp-item">
              <span class="timestamp-label">{{
                'admin.jobDetail.completed' | translate
              }}</span>
              <span class="timestamp-value">{{
                job()!.completed_at | date : 'medium'
              }}</span>
            </div>
            } @if (job()!.duration_seconds) {
            <div class="timestamp-item">
              <span class="timestamp-label">{{
                'admin.jobDetail.duration' | translate
              }}</span>
              <span class="timestamp-value">{{
                formatDuration(job()!.duration_seconds!)
              }}</span>
            </div>
            }
          </div>

          @if (job()!.status === 'running' || job()!.status === 'pending') {
          <div class="card-actions">
            <button
              class="btn btn-secondary"
              (click)="cancelJob()"
              [disabled]="actionLoading()"
            >
              @if (actionLoading()) {
              <div class="loading-spinner small"></div>
              } @else {
              <img
                src="/icons/x-circle.svg"
                alt="Cancel"
                width="16"
                height="16"
              />
              }
              {{ 'admin.jobDetail.cancel' | translate }}
            </button>
          </div>
          } @if (job()!.status === 'failed') {
          <div class="card-actions">
            <button
              class="btn btn-primary"
              (click)="retryJob()"
              [disabled]="actionLoading()"
            >
              @if (actionLoading()) {
              <div class="loading-spinner small"></div>
              } @else {
              <img
                src="/icons/refresh.svg"
                alt="Retry"
                width="16"
                height="16"
              />
              }
              {{ 'admin.jobDetail.retry' | translate }}
            </button>
          </div>
          }
        </div>

        @if (job()!.status === 'failed' && job()!.error_details) {
        <div class="detail-card error-card">
          <div class="card-header">
            <h2>{{ 'admin.jobDetail.errorDetails' | translate }}</h2>
          </div>
          <div class="error-content">
            <div class="error-message">
              <img
                src="/icons/alert-triangle.svg"
                alt="Error"
                width="20"
                height="20"
              />
              <span>{{ job()!.error_message }}</span>
            </div>
            <pre class="error-details">{{ job()!.error_details }}</pre>
          </div>
        </div>
        }

        @if (job()!.input_params) {
        <div class="detail-card">
          <div class="card-header">
            <h2>{{ 'admin.jobDetail.inputParameters' | translate }}</h2>
          </div>
          <pre class="json-content">{{ formatJson(job()!.input_params) }}</pre>
        </div>
        }

        @if (job()!.result_summary) {
        <div class="detail-card">
          <div class="card-header">
            <h2>{{ 'admin.jobDetail.resultSummary' | translate }}</h2>
          </div>
          <pre class="json-content">{{
            formatJson(job()!.result_summary)
          }}</pre>
        </div>
        }

        @if (job()!.events && job()!.events.length > 0) {
        <div class="detail-card timeline-card">
          <div class="card-header">
            <h2>{{ 'admin.jobDetail.eventTimeline' | translate }}</h2>
          </div>
          <div class="timeline">
            @for (event of job()!.events; track event.id) {
            <div class="timeline-item">
              <div class="timeline-content">
                <div class="timeline-header">
                  <span class="event-type">{{ event.event_type }}</span>
                  <span class="event-time">{{
                    event.created_at | date : 'short'
                  }}</span>
                </div>
                @if (event.old_status && event.new_status) {
                <div class="status-change">
                  <span
                    class="status-badge status-small"
                    [class]="'status-' + event.old_status"
                    >{{ event.old_status }}</span
                  >
                  <span>
                    ->
                  </span>
                  <span
                    class="status-badge status-small"
                    [class]="'status-' + event.new_status"
                    >{{ event.new_status }}</span
                  >
                </div>
                } @if (event.message) {
                <p class="event-message">{{ event.message }}</p>
                }
              </div>
            </div>
            }
          </div>
        </div>
        }

        <div class="detail-card metadata-card">
          <div class="card-header">
            <h2>{{ 'admin.jobDetail.metadata' | translate }}</h2>
          </div>
          <div class="metadata-grid">
            <div class="metadata-item">
              <span class="metadata-label">{{
                'admin.jobDetail.userId' | translate
              }}</span>
              <code class="metadata-value">{{ job()!.user_id }}</code>
            </div>
            @if (job()!.datasource_id) {
            <div class="metadata-item">
              <span class="metadata-label">{{
                'admin.jobDetail.datasourceId' | translate
              }}</span>
              <code class="metadata-value">{{ job()!.datasource_id }}</code>
            </div>
            } @if (job()!.knowledge_base_id) {
            <div class="metadata-item">
              <span class="metadata-label">{{
                'admin.jobDetail.knowledgeBaseId' | translate
              }}</span>
              <code class="metadata-value">{{ job()!.knowledge_base_id }}</code>
            </div>
            }
          </div>
        </div>
      </div>
      }
    </div>
  `,
  styles: `
    .job-detail {
      padding: 2rem;
      max-width: 1200px;
      margin: 0 auto;
      background: aliceblue;
    }

    .detail-header {
      margin-bottom: 2rem;
    }

    .detail-content {
      display: flex;
      flex-direction: column;
      gap: 1.5rem;
    }

    .detail-card {
      background: white;
      border-radius: 12px;
      border: 1px solid #e2e8f0;
      padding: 1.5rem;

      &.error-card {
        border-color: #fecaca;
        background: #fef2f2;
      }

      .card-header {
        display: flex;
        justify-content: space-between;
        align-items: center;
        margin-bottom: 1.5rem;

        h1, h2 {
          margin: 0;
          font-size: 1.5rem;
          font-weight: 600;
        }

        h2 {
          font-size: 1.25rem;
        }
      }

      .card-actions {
        margin-top: 1.5rem;
        padding-top: 1.5rem;
        border-top: 1px solid #e2e8f0;
        display: flex;
        gap: 1rem;
      }
    }

    .overview-card {
      .job-title {
        display: flex;
        align-items: center;
        gap: 1rem;

        h1 {
          text-transform: capitalize;
        }

        .job-id {
          display: block;
          font-size: 0.875rem;
          color: #64748b;
          font-weight: 400;
        }
      }
    }

    .status-badge {
      padding: 0.5rem 1rem;
      border-radius: 8px;
      font-size: 0.875rem;
      font-weight: 600;
      text-transform: uppercase;

      &.status-small {
        padding: 0.25rem 0.5rem;
        font-size: 0.75rem;
      }

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

    .progress-section {
      margin-top: 1.5rem;
      padding: 1rem;
      background: #f8fafc;
      border-radius: 8px;

      .progress-header {
        display: flex;
        justify-content: space-between;
        align-items: center;
        margin-bottom: 0.5rem;
        gap: 1rem;

        .progress-label {
          font-weight: 500;
          flex: 1;
          min-width: 0;
          overflow: hidden;
          text-overflow: ellipsis;
          white-space: nowrap;
        }

        .progress-header-right {
          display: flex;
          align-items: center;
          gap: 0.75rem;
          flex-shrink: 0;
        }

        .progress-percentage {
          font-weight: 700;
          color: #3b82f6;
        }
      }

      .btn-toggle-files {
        display: inline-flex;
        align-items: center;
        gap: 0.375rem;
        padding: 0.25rem 0.625rem;
        background: white;
        border: 1px solid #e2e8f0;
        border-radius: 6px;
        font-size: 0.8125rem;
        font-weight: 500;
        color: #475569;
        cursor: pointer;
        transition: background 0.15s, border-color 0.15s;

        &:hover {
          background: #f1f5f9;
          border-color: #cbd5e1;
        }

        .chevron {
          display: inline-block;
          transition: transform 0.2s;
          font-size: 0.875rem;
          line-height: 1;

          &.chevron-open {
            transform: rotate(180deg);
          }
        }
      }

      .progress-bar {
        height: 12px;
        background: #e2e8f0;
        border-radius: 6px;
        overflow: hidden;
        margin-bottom: 0.5rem;

        .progress-fill {
          height: 100%;
          background: #3b82f6;
          transition: width 0.3s;
        }
      }

      .progress-details {
        font-size: 0.875rem;
        color: #64748b;
      }
    }

    .file-list {
      margin-top: 1rem;
      max-height: 400px;
      overflow-y: auto;
      background: white;
      border: 1px solid #e2e8f0;
      border-radius: 8px;

      .file-row {
        padding: 0.625rem 0.875rem;
        border-bottom: 1px solid #f1f5f9;

        &:last-child {
          border-bottom: none;
        }

        .file-row-main {
          display: flex;
          align-items: center;
          gap: 0.75rem;
          justify-content: space-between;
        }

        .file-name {
          flex: 1;
          min-width: 0;
          font-size: 0.875rem;
          color: #0f172a;
          overflow: hidden;
          text-overflow: ellipsis;
          white-space: nowrap;
        }

        .file-error {
          margin-top: 0.25rem;
          font-size: 0.75rem;
          color: #991b1b;
          overflow: hidden;
          text-overflow: ellipsis;
          white-space: nowrap;
        }

        .file-error-detail {
          margin-top: 0.25rem;
          font-size: 0.75rem;

          summary {
            cursor: pointer;
            color: #64748b;
            user-select: none;

            &:hover {
              color: #334155;
            }
          }

          pre {
            margin: 0.375rem 0 0;
            padding: 0.5rem 0.625rem;
            background: #f8fafc;
            border: 1px solid #e2e8f0;
            border-radius: 4px;
            color: #475569;
            font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
            font-size: 0.6875rem;
            white-space: pre-wrap;
            word-break: break-word;
            max-height: 240px;
            overflow: auto;
          }
        }
      }
    }

    .file-state-badge {
      flex-shrink: 0;
      padding: 0.125rem 0.5rem;
      border-radius: 999px;
      font-size: 0.6875rem;
      font-weight: 600;
      text-transform: uppercase;
      letter-spacing: 0.02em;
      background: #f3f4f6;
      color: #374151;

      &.file-state-pending {
        background: #f3f4f6;
        color: #6b7280;
      }
      &.file-state-downloading {
        background: #dbeafe;
        color: #1e40af;
      }
      &.file-state-downloaded {
        background: #bfdbfe;
        color: #1e3a8a;
      }
      &.file-state-ingesting {
        background: #fef3c7;
        color: #92400e;
      }
      &.file-state-ingested {
        background: #d1fae5;
        color: #065f46;
      }
      &.file-state-skipped {
        background: #f3f4f6;
        color: #6b7280;
      }
      &.file-state-failed {
        background: #fee2e2;
        color: #991b1b;
      }
    }

    .timestamps-grid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
      gap: 1.5rem;
      margin-top: 1.5rem;
      padding-top: 1.5rem;
      border-top: 1px solid #e2e8f0;

      .timestamp-item {
        display: flex;
        flex-direction: column;
        gap: 0.5rem;

        .timestamp-label {
          font-size: 0.875rem;
          color: #64748b;
          font-weight: 500;
        }

        .timestamp-value {
          font-weight: 600;
        }
      }
    }

    .error-content {
      .error-message {
        display: flex;
        align-items: center;
        gap: 0.75rem;
        padding: 1rem;
        background: white;
        border-radius: 8px;
        border: 1px solid #fecaca;
        margin-bottom: 1rem;
        color: #991b1b;
        font-weight: 500;
      }

      .error-details {
        margin: 0;
        padding: 1rem;
        background: white;
        border: 1px solid #fecaca;
        border-radius: 8px;
        overflow-x: auto;
        font-size: 0.875rem;
        color: #991b1b;
      }
    }

    .json-content {
      margin: 0;
      padding: 1rem;
      background: #f8fafc;
      border: 1px solid #e2e8f0;
      border-radius: 8px;
      overflow-x: auto;
      font-size: 0.875rem;
      line-height: 1.5;
    }

    .timeline {
      position: relative;
      padding-left: 2rem;

      &::before {
        content: '';
        position: absolute;
        left: 0.75rem;
        top: 0;
        bottom: 0;
        width: 2px;
        background: #e2e8f0;
      }

      .timeline-item {
        position: relative;
        padding-bottom: 2rem;

        &:last-child {
          padding-bottom: 0;
        }

        .timeline-marker {
          position: absolute;
          left: -1.5rem;
          top: 0.25rem;
          width: 2rem;
          height: 2rem;
          border-radius: 50%;
          background: white;
          border: 2px solid #e2e8f0;
          display: flex;
          align-items: center;
          justify-content: center;

          &.event-success {
            border-color: #22c55e;
            background: #f0fdf4;
          }

          &.event-error {
            border-color: #ef4444;
            background: #fef2f2;
          }

          &.event-warning {
            border-color: #f59e0b;
            background: #fffbeb;
          }
        }

        .timeline-content {
          .timeline-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 0.5rem;

            .event-type {
              font-weight: 600;
              text-transform: capitalize;
            }

            .event-time {
              font-size: 0.875rem;
              color: #64748b;
            }
          }

          .status-change {
            display: flex;
            align-items: center;
            gap: 0.5rem;
            margin: 0.75rem 0;
          }

          .event-message {
            margin: 0.5rem 0 0;
            color: #475569;
            font-size: 0.875rem;
          }
        }
      }
    }

    .metadata-grid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(250px, 1fr));
      gap: 1.5rem;

      .metadata-item {
        display: flex;
        flex-direction: column;
        gap: 0.5rem;

        .metadata-label {
          font-size: 0.875rem;
          color: #64748b;
          font-weight: 500;
        }

        .metadata-value {
          padding: 0.5rem;
          background: #f8fafc;
          border: 1px solid #e2e8f0;
          border-radius: 6px;
          font-size: 0.875rem;
          word-break: break-all;
        }
      }
    }

    .loading-container,
    .error-container {
      display: flex;
      flex-direction: column;
      align-items: center;
      justify-content: center;
      padding: 4rem 2rem;
      gap: 1rem;
    }

    .loading-spinner {
      width: 40px;
      height: 40px;
      border: 4px solid #e2e8f0;
      border-top-color: #3b82f6;
      border-radius: 50%;
      animation: spin 1s linear infinite;

      &.small {
        width: 16px;
        height: 16px;
        border-width: 2px;
      }
    }

    @keyframes spin {
      to {
        transform: rotate(360deg);
      }
    }
  `,
})
export class AdminJobDetailComponent implements OnInit, OnDestroy {
  private route = inject(ActivatedRoute);
  private router = inject(Router);
  private adminService = inject(AdminService);

  loading = signal(false);
  error = signal<string | null>(null);
  job = signal<JobDetail | null>(null);
  actionLoading = signal(false);
  filesExpanded = signal(false);

  hasFiles = computed(() => {
    const j = this.job();
    return !!j?.files && j.files.length > 0;
  });

  toggleFilesExpanded(): void {
    this.filesExpanded.update((v) => !v);
  }

  private refreshInterval?: ReturnType<typeof setInterval>;
  private readonly POLL_INTERVAL = 5000;

  ngOnInit(): void {
    const id = this.route.snapshot.paramMap.get('id');
    if (id) {
      this.loadJob(id);
    } else {
      this.error.set('No job ID provided');
    }
  }

  ngOnDestroy(): void {
    this.stopPolling();
  }

  loadJob(id?: string): void {
    const jobId = id || this.route.snapshot.paramMap.get('id');
    if (!jobId) return;

    this.loading.set(true);
    this.error.set(null);

    this.adminService.getJobDetail(jobId).subscribe({
      next: (job) => {
        this.job.set(job);
        this.loading.set(false);

        if (job.status === 'running' || job.status === 'pending') {
          this.startPolling(jobId);
        } else {
          this.stopPolling();
        }
      },
      error: (err) => {
        console.error('Error loading job:', err);
        this.error.set('Failed to load job details');
        this.loading.set(false);
        this.stopPolling();
      },
    });
  }

  private startPolling(jobId: string): void {
    this.stopPolling();

    this.refreshInterval = setInterval(() => {
      this.adminService.getJobDetail(jobId).subscribe({
        next: (job) => {
          const currentStatus = this.job()?.status;
          this.job.set(job);

          if (
            currentStatus !== job.status &&
            job.status !== 'running' &&
            job.status !== 'pending'
          ) {
            this.stopPolling();
          }
        },
        error: (err) => {
          // Keep polling on transient errors.
          console.error('Error polling job:', err);
        },
      });
    }, this.POLL_INTERVAL);
  }

  private stopPolling(): void {
    if (this.refreshInterval) {
      clearInterval(this.refreshInterval);
      this.refreshInterval = undefined;
    }
  }

  cancelJob(): void {
    const job = this.job();
    if (!job || this.actionLoading()) return;

    if (!confirm('Are you sure you want to cancel this job?')) return;

    this.actionLoading.set(true);

    this.adminService.cancelJob(job.id).subscribe({
      next: () => {
        this.actionLoading.set(false);
        this.loadJob(job.id);
      },
      error: (err) => {
        console.error('Error cancelling job:', err);
        alert('Failed to cancel job');
        this.actionLoading.set(false);
      },
    });
  }

  retryJob(): void {
    const job = this.job();
    if (!job || this.actionLoading()) return;

    this.actionLoading.set(true);

    this.adminService.retryJob(job.id).subscribe({
      next: () => {
        this.actionLoading.set(false);
        this.loadJob(job.id);
      },
      error: (err) => {
        console.error('Error retrying job:', err);
        alert('Failed to retry job');
        this.actionLoading.set(false);
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

  getEventClass(event: any): string {
    if (
      event.event_type.includes('complete') ||
      event.new_status === 'completed'
    ) {
      return 'event-success';
    }
    if (event.event_type.includes('fail') || event.new_status === 'failed') {
      return 'event-error';
    }
    if (
      event.event_type.includes('cancel') ||
      event.new_status === 'cancelled'
    ) {
      return 'event-warning';
    }
    return '';
  }

  getEventIcon(event: any): string {
    if (
      event.event_type.includes('complete') ||
      event.new_status === 'completed'
    ) {
      return '/icons/check-circle.svg';
    }
    if (event.event_type.includes('fail') || event.new_status === 'failed') {
      return '/icons/x-circle.svg';
    }
    if (
      event.event_type.includes('cancel') ||
      event.new_status === 'cancelled'
    ) {
      return '/icons/alert-triangle.svg';
    }
    return '/icons/info.svg';
  }

  formatDuration(seconds: number): string {
    if (seconds < 60) return `${Math.round(seconds)}s`;
    const minutes = Math.floor(seconds / 60);
    const remainingSeconds = Math.round(seconds % 60);
    if (minutes < 60) return `${minutes}m ${remainingSeconds}s`;
    const hours = Math.floor(minutes / 60);
    const remainingMinutes = minutes % 60;
    return `${hours}h ${remainingMinutes}m`;
  }

  formatJson(obj: any): string {
    return JSON.stringify(obj, null, 2);
  }
}
