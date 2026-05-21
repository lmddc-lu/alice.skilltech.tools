import { HttpInterceptorFn } from '@angular/common/http';
import { inject } from '@angular/core';
import { Router } from '@angular/router';
import { HttpClient } from '@angular/common/http';
import { catchError, switchMap, throwError, Subject, filter, take } from 'rxjs';
import { AuthService } from '../services/core/auth.service';
import { environment } from '../../environments/environment';

let isRefreshing = false;
let refreshResult$ = new Subject<boolean>();

export const authInterceptor: HttpInterceptorFn = (req, next) => {
  const authService = inject(AuthService);
  const router = inject(Router);
  const http = inject(HttpClient);

  if (!req.url.startsWith('/api/')) {
    return next(req);
  }

  const authReq = req.clone({
    withCredentials: true,
  });

  return next(authReq).pipe(
    catchError((err) => {
      if (err.status !== 401) {
        return throwError(() => err);
      }

      // Skip refresh on the refresh/user_info endpoints to avoid infinite loops.
      const isRefreshReq = req.url.includes('/oauth/refresh');
      const isUserInfoReq = req.url.includes('/oauth/user_info');

      if (isRefreshReq || isUserInfoReq) {
        handleLogout(authService, router);
        return throwError(() => err);
      }

      if (isRefreshing) {
        return refreshResult$.pipe(
          filter((success) => success !== null),
          take(1),
          switchMap((success) => {
            if (success) {
              return next(authReq);
            }
            return throwError(() => err);
          })
        );
      }

      isRefreshing = true;
      refreshResult$ = new Subject<boolean>();

      return http
        .post(`${environment.apiBaseUrl}/oauth/refresh`, null, {
          withCredentials: true,
        })
        .pipe(
          switchMap(() => {
            isRefreshing = false;
            refreshResult$.next(true);
            refreshResult$.complete();
            return next(authReq);
          }),
          catchError((refreshErr) => {
            isRefreshing = false;
            refreshResult$.next(false);
            refreshResult$.complete();
            handleLogout(authService, router);
            return throwError(() => refreshErr);
          })
        );
    })
  );
};

function handleLogout(authService: AuthService, router: Router): void {
  const currentUrl = router.url;
  if (
    currentUrl &&
    currentUrl !== '/' &&
    !currentUrl.includes('/dashboard')
  ) {
    sessionStorage.setItem('returnUrl', currentUrl);
  }
  authService.logout();
}
