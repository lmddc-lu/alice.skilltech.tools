import { Injectable, computed, inject, signal } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Router } from '@angular/router';
import { Observable, catchError, map, of, shareReplay, tap } from 'rxjs';
import { environment } from '../../../environments/environment';
import { UserInfoI, UserValidationI } from '../../interfaces/userinfo-i';

@Injectable({
  providedIn: 'root',
})
export class AuthService {
  private http = inject(HttpClient);
  private router = inject(Router);

  private readonly _userInfo = signal<UserInfoI | null>(null);
  readonly userInfo = this._userInfo.asReadonly();

  readonly isAuthenticated = computed(() => this._userInfo() !== null);
  readonly isAdmin = computed(() => this._userInfo()?.role === 'admin');
  readonly isActive = computed(() => this._userInfo()?.is_active === true);

  private lastVerification = 0;
  private verificationInterval = 5 * 60 * 1000;
  private inflight$: Observable<UserInfoI> | null = null;

  constructor() {
    const cachedUserInfo = localStorage.getItem('userInfo');
    if (cachedUserInfo) {
      try {
        this._userInfo.set(JSON.parse(cachedUserInfo));
      } catch {
        localStorage.removeItem('userInfo');
      }
    }
  }

  login(): void {
    window.location.href = `${environment.apiBaseUrl}/oauth/login`;
  }

  // Concurrent callers during a fetch share the same in-flight request.
  getUserInfo(): Observable<UserInfoI> {
    const current = this._userInfo();
    if (current) return of(current);
    if (this.inflight$) return this.inflight$;

    this.inflight$ = this.http
      .get<UserInfoI>(`${environment.apiBaseUrl}/oauth/user_info`, {
        withCredentials: true,
      })
      .pipe(
        tap((userInfo) => {
          this._userInfo.set(userInfo);
          localStorage.setItem('userInfo', JSON.stringify(userInfo));
          this.inflight$ = null;
          this.handleReturnUrl();
        }),
        catchError((error) => {
          this._userInfo.set(null);
          localStorage.removeItem('userInfo');
          this.inflight$ = null;
          console.error('Failed to get user info:', error);
          throw error;
        }),
        shareReplay(1)
      );
    return this.inflight$;
  }

  private handleReturnUrl(): void {
    const returnUrl = sessionStorage.getItem('returnUrl');
    if (returnUrl) {
      sessionStorage.removeItem('returnUrl');
      // Full reload - coming back from an OAuth redirect.
      setTimeout(() => {
        window.location.href = returnUrl;
      }, 100);
    }
  }

  refreshUserInfo(): Observable<UserInfoI> {
    this.inflight$ = null;
    this._userInfo.set(null);
    return this.getUserInfo();
  }

  checkSession(): Observable<UserValidationI> {
    const now = Date.now();
    const current = this._userInfo();

    if (
      this.lastVerification > 0 &&
      now - this.lastVerification < this.verificationInterval &&
      current
    ) {
      return of({
        is_valid: true,
        id: current.id,
        role: current.role,
        is_active: current.is_active,
      });
    }

    return this.getUserInfo().pipe(
      map((userInfo) => {
        this.lastVerification = now;
        return {
          is_valid: !!userInfo?.id,
          id: userInfo.id,
          role: userInfo.role,
          is_active: userInfo.is_active,
        };
      }),
      catchError(() => {
        this.lastVerification = 0;
        return of({
          is_valid: false,
          id: null,
          role: null,
          is_active: null,
        });
      })
    );
  }

  logout(): void {
    localStorage.removeItem('userInfo');
    this._userInfo.set(null);
    this.lastVerification = 0;
    this.inflight$ = null;

    window.location.href = `${environment.apiBaseUrl}/oauth/logout`;
  }
}
