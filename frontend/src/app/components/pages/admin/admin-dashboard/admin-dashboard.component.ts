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
import { RouterLink } from '@angular/router';
import { TranslatePipe } from '@ngx-translate/core';
import {
  AdminService,
  DashboardData,
  HealthStatus,
} from '../../../../services/admin/admin.service';

@Component({
  selector: 'app-admin-dashboard',
  imports: [CommonModule, RouterLink, TranslatePipe],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <div class="admin-dashboard">
      <div class="dashboard-header">
        <h1>{{ 'admin.dashboard.title' | translate }}</h1>
        <div class="header-actions">
          <button class="btn btn-secondary" [routerLink]="['/admin/jobs']">
            <img src="/icons/package.svg" alt="Jobs" width="16" height="16" />
            {{ 'admin.dashboard.viewAllJobs' | translate }}
          </button>
          <button
            class="btn btn-secondary"
            (click)="refresh()"
            [disabled]="loading()"
          >
            <img
              src="/icons/refresh.svg"
              alt="Refresh"
              width="16"
              height="16"
            />
            {{ 'admin.dashboard.refresh' | translate }}
          </button>
        </div>
      </div>

      @if (loading()) {
      <div class="loading-container">
        <div class="loading-spinner"></div>
        <p>{{ 'admin.dashboard.loading' | translate }}</p>
      </div>
      } @else if (error()) {
      <div class="error-container">
        <p>{{ error() }}</p>
        <button class="btn btn-primary" (click)="refresh()">
          {{ 'admin.dashboard.retry' | translate }}
        </button>
      </div>
      } @else {
      <div class="health-banner" [class]="healthStatusClass()">
        <div class="health-icon">
          <img [src]="healthStatusIcon()" alt="Health" width="24" height="24" />
        </div>
        <div class="health-info">
          <h3>{{ 'admin.dashboard.systemHealth' | translate }}</h3>
          <p>{{ healthStatusMessage() }}</p>
        </div>
      </div>

      <div class="stats-grid">
        <div class="stat-card">
          <div class="stat-icon total">
            <img src="/icons/package.svg" alt="Jobs" width="24" height="24" />
          </div>
          <div class="stat-content">
            <span class="stat-label">{{
              'admin.dashboard.totalJobs' | translate
            }}</span>
            <span class="stat-value">{{ stats()?.total || 0 }}</span>
          </div>
        </div>

        <div class="stat-card">
          <div class="stat-icon success">
            <img
              src="/icons/check-circle.svg"
              alt="Success"
              width="24"
              height="24"
            />
          </div>
          <div class="stat-content">
            <span class="stat-label">{{
              'admin.dashboard.successRate' | translate
            }}</span>
            <span class="stat-value">{{ successRateDisplay() }}</span>
          </div>
        </div>

        <div class="stat-card">
          <div class="stat-icon running">
            <img
              src="/icons/refresh.svg"
              alt="Running"
              width="24"
              height="24"
            />
          </div>
          <div class="stat-content">
            <span class="stat-label">{{
              'admin.dashboard.activeJobs' | translate
            }}</span>
            <span class="stat-value">{{
              stats()?.by_status?.running || 0
            }}</span>
          </div>
        </div>

        <div class="stat-card">
          <div class="stat-icon failed">
            <img
              src="/icons/x-circle.svg"
              alt="Failed"
              width="24"
              height="24"
            />
          </div>
          <div class="stat-content">
            <span class="stat-label">{{
              'admin.dashboard.failedJobs' | translate
            }}</span>
            <span class="stat-value">{{
              stats()?.by_status?.failed || 0
            }}</span>
          </div>
        </div>
      </div>

      @if (activeJobs().length > 0) {
      <div class="section-card">
        <div class="section-header">
          <h2>{{ 'admin.dashboard.activeJobs' | translate }}</h2>
          <a [routerLink]="['/admin/jobs']" class="btn btn-ghost">
            {{ 'admin.dashboard.viewAll' | translate }}
          </a>
        </div>
        <div class="jobs-list">
          @for (job of activeJobs(); track job.id) {
          <div class="job-item" [routerLink]="['/admin/jobs', job.id]">
            <div class="job-icon">
              <img
                [src]="getJobTypeIcon(job.job_type)"
                alt="Job"
                width="20"
                height="20"
              />
            </div>
            <div class="job-info">
              <span class="job-type">{{ job.job_type }}</span>
              <span class="job-id">{{ job.id }}</span>
            </div>
            @if (job.progress) {
            <div class="job-progress">
              <div class="progress-bar">
                <div
                  class="progress-fill"
                  [style.width.%]="job.progress.percentage"
                ></div>
              </div>
              <span class="progress-text">{{ job.progress.percentage }}%</span>
            </div>
            }
            <span class="job-status" [class]="'status-' + job.status">
              {{ job.status }}
            </span>
          </div>
          }
        </div>
      </div>
      }

      @if (recentFailures().length > 0) {
      <div class="section-card">
        <div class="section-header">
          <h2>{{ 'admin.dashboard.recentFailures' | translate }}</h2>
        </div>
        <div class="failures-list">
          @for (job of recentFailures(); track job.id) {
          <div class="failure-item" [routerLink]="['/admin/jobs', job.id]">
            <div class="failure-icon">
              <img
                src="/icons/alert-triangle.svg"
                alt="Failed"
                width="20"
                height="20"
              />
            </div>
            <div class="failure-info">
              <span class="failure-type">{{ job.job_type }}</span>
              <span class="failure-message">{{
                job.error_message || 'Unknown error'
              }}</span>
              <span class="failure-time">{{
                job.completed_at | date : 'short'
              }}</span>
            </div>
          </div>
          }
        </div>
      </div>
      }

      @if (health()?.queues && health()!.queues.length > 0) {
      <div class="section-card">
        <div class="section-header">
          <h2>{{ 'admin.dashboard.queueStatus' | translate }}</h2>
        </div>
        <div class="queues-grid">
          @for (queue of health()!.queues; track queue.name) {
          <div class="queue-card" [class.warning]="!queue.is_healthy">
            <div class="queue-header">
              <span class="queue-name">{{ queue.name }}</span>
              @if (!queue.is_healthy) {
              <span class="queue-warning">
                <img
                  src="/icons/alert-triangle.svg"
                  alt="Warning"
                  width="16"
                  height="16"
                />
              </span>
              }
            </div>
            <div class="queue-stats">
              <div class="queue-stat">
                <span class="stat-label">Ready</span>
                <span class="stat-value">{{ queue.messages_ready }}</span>
              </div>
              <div class="queue-stat">
                <span class="stat-label">Unacked</span>
                <span class="stat-value">{{ queue.messages_unacked }}</span>
              </div>
              <div class="queue-stat">
                <span class="stat-label">Consumers</span>
                <span class="stat-value">{{ queue.consumers }}</span>
              </div>
            </div>
            @if (queue.warning) {
            <p class="queue-warning-message">{{ queue.warning }}</p>
            }
          </div>
          }
        </div>
      </div>
      } }
    </div>
  `,
  styles: `
    .admin-dashboard {
      padding: 2rem;
      max-width: 1400px;
      margin: 0 auto;
      background-color: aliceblue;
    }

    .dashboard-header {
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

    .health-banner {
      display: flex;
      align-items: center;
      gap: 1rem;
      padding: 1.5rem;
      border-radius: 12px;
      margin-bottom: 2rem;
      border: 2px solid;

      &.healthy {
        background: #f0fdf4;
        border-color: #22c55e;
      }

      &.warning {
        background: #fffbeb;
        border-color: #f59e0b;
      }

      &.error {
        background: #fef2f2;
        border-color: #ef4444;
      }

      .health-icon {
        display: flex;
        align-items: center;
        justify-content: center;
      }

      .health-info {
        h3 {
          margin: 0 0 0.25rem 0;
          font-size: 1.125rem;
          font-weight: 600;
        }

        p {
          margin: 0;
          color: #64748b;
        }
      }
    }

    .stats-grid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(250px, 1fr));
      gap: 1.5rem;
      margin-bottom: 2rem;
    }

    .stat-card {
      display: flex;
      align-items: center;
      gap: 1rem;
      padding: 1.5rem;
      background: white;
      border-radius: 12px;
      border: 1px solid #e2e8f0;

      .stat-icon {
        display: flex;
        align-items: center;
        justify-content: center;
        width: 48px;
        height: 48px;
        border-radius: 10px;

        &.total {
          background: #f0f9ff;
        }
        &.success {
          background: #f0fdf4;
        }
        &.running {
          background: #fef3c7;
        }
        &.failed {
          background: #fef2f2;
        }
      }

      .stat-content {
        display: flex;
        flex-direction: column;
        gap: 0.25rem;

        .stat-label {
          font-size: 0.875rem;
          color: #64748b;
        }

        .stat-value {
          font-size: 1.875rem;
          font-weight: 700;
        }
      }
    }

    .section-card {
      background: white;
      border-radius: 12px;
      border: 1px solid #e2e8f0;
      padding: 1.5rem;
      margin-bottom: 2rem;

      .section-header {
        display: flex;
        justify-content: space-between;
        align-items: center;
        margin-bottom: 1.5rem;

        h2 {
          margin: 0;
          font-size: 1.25rem;
          font-weight: 600;
        }
      }
    }

    .jobs-list,
    .failures-list {
      display: flex;
      flex-direction: column;
      gap: 1rem;
    }

    .job-item {
      display: flex;
      align-items: center;
      gap: 1rem;
      padding: 1rem;
      border-radius: 8px;
      border: 1px solid #e2e8f0;
      cursor: pointer;
      transition: all 0.2s;

      &:hover {
        border-color: #94a3b8;
        box-shadow: 0 2px 8px rgba(0, 0, 0, 0.05);
      }

      .job-icon {
        display: flex;
        align-items: center;
        justify-content: center;
      }

      .job-info {
        display: flex;
        flex-direction: column;
        gap: 0.25rem;
        flex: 1;

        .job-type {
          font-weight: 600;
        }

        .job-id {
          font-size: 0.875rem;
          color: #64748b;
        }
      }

      .job-progress {
        display: flex;
        align-items: center;
        gap: 0.5rem;
        min-width: 150px;

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
          font-size: 0.875rem;
          font-weight: 600;
        }
      }

      .job-status {
        padding: 0.375rem 0.75rem;
        border-radius: 6px;
        font-size: 0.875rem;
        font-weight: 500;

        &.status-running {
          background: #fef3c7;
          color: #92400e;
        }

        &.status-pending {
          background: #f3f4f6;
          color: #374151;
        }
      }
    }

    .failure-item {
      display: flex;
      align-items: flex-start;
      gap: 1rem;
      padding: 1rem;
      border-radius: 8px;
      border: 1px solid #fecaca;
      background: #fef2f2;
      cursor: pointer;
      transition: all 0.2s;

      &:hover {
        border-color: #ef4444;
      }

      .failure-icon {
        display: flex;
        align-items: center;
        justify-content: center;
        color: #ef4444;
      }

      .failure-info {
        display: flex;
        flex-direction: column;
        gap: 0.25rem;
        flex: 1;

        .failure-type {
          font-weight: 600;
        }

        .failure-message {
          color: #64748b;
          font-size: 0.875rem;
        }

        .failure-time {
          color: #94a3b8;
          font-size: 0.875rem;
        }
      }
    }

    .queues-grid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
      gap: 1rem;
    }

    .queue-card {
      padding: 1rem;
      border-radius: 8px;
      border: 1px solid #e2e8f0;

      &.warning {
        border-color: #f59e0b;
        background: #fffbeb;
      }

      .queue-header {
        display: flex;
        justify-content: space-between;
        align-items: center;
        margin-bottom: 1rem;

        .queue-name {
          font-weight: 600;
        }

        .queue-warning {
          color: #f59e0b;
        }
      }

      .queue-stats {
        display: grid;
        grid-template-columns: repeat(3, 1fr);
        gap: 1rem;

        .queue-stat {
          display: flex;
          flex-direction: column;
          gap: 0.25rem;

          .stat-label {
            font-size: 0.875rem;
            color: #64748b;
          }

          .stat-value {
            font-size: 1.5rem;
            font-weight: 700;
          }
        }
      }

      .queue-warning-message {
        margin-top: 0.75rem;
        font-size: 0.875rem;
        color: #92400e;
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
  `,
})
export class AdminDashboardComponent implements OnInit, OnDestroy {
  private adminService = inject(AdminService);

  loading = signal(false);
  error = signal<string | null>(null);
  dashboardData = signal<DashboardData | null>(null);
  health = signal<HealthStatus | null>(null);

  private refreshInterval?: ReturnType<typeof setInterval>;

  stats = computed(() => this.dashboardData()?.stats || null);
  activeJobs = computed(() => this.dashboardData()?.active_jobs || []);
  recentFailures = computed(() => this.dashboardData()?.recent_failures || []);

  successRateDisplay = computed(() => {
    const rate = this.stats()?.success_rate;
  
    return rate !== undefined && rate !== null ? `${rate * 100}%` : '0%';
  });

  healthStatusClass = computed(() => {
    const status = this.health()?.overall_status;
    return status || 'healthy';
  });

  healthStatusIcon = computed(() => {
    const status = this.health()?.overall_status;
    return status === 'healthy'
      ? '/icons/check-circle.svg'
      : status === 'warning'
      ? '/icons/alert-triangle.svg'
      : '/icons/x-circle.svg';
  });

  healthStatusMessage = computed(() => {
    const health = this.health();
    if (!health) return 'Loading...';

    if (health.overall_status === 'healthy') {
      return 'All systems operational';
    } else if (health.overall_status === 'warning') {
      return 'Some systems need attention';
    } else {
      return 'System experiencing issues';
    }
  });

  ngOnInit(): void {
    this.loadData();
    this.startAutoRefresh();
  }

  ngOnDestroy(): void {
    this.stopAutoRefresh();
  }

  loadData(): void {
    this.loading.set(true);
    this.error.set(null);

    Promise.all([
      this.adminService.getDashboard().toPromise(),
      this.adminService.getHealth().toPromise(),
    ])
      .then(([dashboard, health]) => {
        this.dashboardData.set(dashboard || null);
        this.health.set(health || null);
        this.loading.set(false);
      })
      .catch((err) => {
        console.error('Error loading admin data:', err);
        this.error.set('Failed to load dashboard data');
        this.loading.set(false);
      });
  }

  refresh(): void {
    this.loadData();
  }

  private startAutoRefresh(): void {
    this.refreshInterval = setInterval(() => {
      this.loadData();
    }, 10000);
  }

  private stopAutoRefresh(): void {
    if (this.refreshInterval) {
      clearInterval(this.refreshInterval);
    }
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
}
