import { Injectable, computed, signal } from '@angular/core';
import { Observable, of } from 'rxjs';
import { UserInfoI, UserValidationI } from '../../app/interfaces/userinfo-i';
import { mockUser, mockAdminUser } from '../fixtures/user.fixture';

@Injectable({ providedIn: 'root' })
export class MockAuthService {
  private readonly _userInfo = signal<UserInfoI | null>(mockUser);
  readonly userInfo = this._userInfo.asReadonly();

  readonly isAuthenticated = computed(() => this._userInfo() !== null);
  readonly isAdmin = computed(() => this._userInfo()?.role === 'admin');
  readonly isActive = computed(() => this._userInfo()?.is_active === true);

  login(): void {
    console.info('[mock] login() — no-op, user already authenticated');
  }

  logout(): void {
    console.info('[mock] logout() — no-op');
  }

  getUserInfo(): Observable<UserInfoI> {
    return of(this._userInfo() ?? mockUser);
  }

  refreshUserInfo(): Observable<UserInfoI> {
    return this.getUserInfo();
  }

  checkSession(): Observable<UserValidationI> {
    const user = this._userInfo() ?? mockUser;
    return of({
      is_valid: true,
      id: user.id,
      role: user.role,
      is_active: user.is_active,
    });
  }

  setAdminMode(isAdmin: boolean): void {
    this._userInfo.set(isAdmin ? mockAdminUser : mockUser);
  }
}
