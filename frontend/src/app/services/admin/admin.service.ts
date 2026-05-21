import { Injectable, inject } from '@angular/core';
import { HttpClient, HttpParams } from '@angular/common/http';
import { Observable } from 'rxjs';
import { environment } from '../../../environments/environment';

export interface HealthStatus {
  rabbitmq_connected: boolean;
  database_connected: boolean;
  queues: QueueInfo[];
  active_jobs: number;
  failed_jobs_24h: number;
  avg_job_duration: number;
  overall_status: 'healthy' | 'warning' | 'error';
}

export interface QueueInfo {
  name: string;
  messages_ready: number;
  messages_unacked: number;
  consumers: number;
  is_healthy: boolean;
  warning: string | null;
}

export interface JobStatistics {
  total: number;
  by_status: {
    pending: number;
    running: number;
    completed: number;
    failed: number;
    cancelled?: number;
  };
  by_type: {
    ingestion: number;
    metadata_sync: number;
    content_sync: number;
  };
  avg_duration_seconds: number;
  success_rate: number;
}

export interface JobProgress {
  current: number;
  total: number;
  message: string;
  percentage: number;
}

export interface Job {
  id: string;
  job_type: 'ingestion' | 'metadata_sync' | 'content_sync';
  status:
    | 'pending'
    | 'running'
    | 'completed'
    | 'failed'
    | 'cancelled'
    | 'stalled';
  user_id: string;
  datasource_id: string | null;
  knowledge_base_id: string | null;
  created_at: string;
  started_at: string | null;
  completed_at: string | null;
  progress: JobProgress | null;
  error_message: string | null;
  duration_seconds: number | null;
}

export type JobFileState =
  | 'pending'
  | 'downloading'
  | 'downloaded'
  | 'ingesting'
  | 'ingested'
  | 'skipped'
  | 'failed';

export interface JobFile {
  id: string;
  external_file_id: string;
  filename: string;
  state: JobFileState;
  error_message: string | null;
  // Verbose converter-level error returned only by admin endpoints.
  error_detail: string | null;
  error_code: string | null;
  created_at: string;
  updated_at: string;
}

export interface JobDetail extends Job {
  input_params: Record<string, any> | null;
  result_summary: Record<string, any> | null;
  error_details: string | null;
  events: JobEvent[];
  files: JobFile[];
}

export interface JobEvent {
  id: string;
  event_type: string;
  old_status: string | null;
  new_status: string;
  message: string | null;
  created_at: string;
}

export interface DashboardData {
  stats: JobStatistics;
  active_jobs: Job[];
  recent_failures: Job[];
  time_range_hours: number;
}

@Injectable({
  providedIn: 'root',
})
export class AdminService {
  private http = inject(HttpClient);
  private baseUrl = `${environment.apiBaseUrl}/admin/monitoring`;

  getHealth(): Observable<HealthStatus> {
    return this.http.get<HealthStatus>(`${this.baseUrl}/health`);
  }

  getDashboard(hours: number = 24): Observable<DashboardData> {
    const params = new HttpParams().set('hours', hours.toString());
    return this.http.get<DashboardData>(`${this.baseUrl}/dashboard`, {
      params,
    });
  }

  getJobs(filters?: {
    job_type?: string;
    status?: string;
    user_id?: string;
    skip?: number;
    limit?: number;
  }): Observable<Job[]> {
    let params = new HttpParams();

    if (filters) {
      Object.entries(filters).forEach(([key, value]) => {
        if (value !== undefined && value !== null) {
          params = params.set(key, value.toString());
        }
      });
    }

    return this.http.get<Job[]>(`${this.baseUrl}/jobs`, { params });
  }

  getJobDetail(jobId: string): Observable<JobDetail> {
    return this.http.get<JobDetail>(`${this.baseUrl}/jobs/${jobId}`);
  }

  getStats(hours: number = 24): Observable<JobStatistics> {
    const params = new HttpParams().set('hours', hours.toString());
    return this.http.get<JobStatistics>(`${this.baseUrl}/stats`, { params });
  }

  cleanupOldJobs(days: number = 30): Observable<{
    message: string;
    deleted_count: number;
    retention_days: number;
  }> {
    const params = new HttpParams().set('days', days.toString());
    return this.http.post<{
      message: string;
      deleted_count: number;
      retention_days: number;
    }>(`${this.baseUrl}/cleanup`, {}, { params });
  }

  cancelJob(jobId: string): Observable<{
    message: string;
    job_id: string;
    status: string;
  }> {
    return this.http.post<{
      message: string;
      job_id: string;
      status: string;
    }>(`${this.baseUrl}/jobs/${jobId}/cancel`, {});
  }

  retryJob(jobId: string): Observable<{
    message: string;
    job_id: string;
    retry_count: number;
    status: string;
  }> {
    return this.http.post<{
      message: string;
      job_id: string;
      retry_count: number;
      status: string;
    }>(`${this.baseUrl}/jobs/${jobId}/retry`, {});
  }
}
