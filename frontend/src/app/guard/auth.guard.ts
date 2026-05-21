import { CanActivateFn, Router } from '@angular/router';
import { inject } from '@angular/core';
import { map } from 'rxjs/operators';
import { UserValidationI } from '../interfaces/userinfo-i';
import { AuthService } from '../services/core/auth.service';

export const authGuard: CanActivateFn = (route, state) => {
  const authService: AuthService = inject(AuthService);
  const router: Router = inject(Router);

  return authService.checkSession().pipe(
    map((userValidation: UserValidationI) => {
      if (userValidation.is_valid) {
        return true;
      } else {
        sessionStorage.setItem('returnUrl', state.url);
        router.navigate(['/']);
        return false;
      }
    })
  );
};
