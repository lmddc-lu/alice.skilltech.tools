import { CanActivateFn, Router } from '@angular/router';
import { inject } from '@angular/core';
import { map } from 'rxjs/operators';
import { UserValidationI } from '../interfaces/userinfo-i';
import { AuthService } from '../services/core/auth.service';

export const adminGuard: CanActivateFn = (route, state) => {
  const authService: AuthService = inject(AuthService);
  const router: Router = inject(Router);

  return authService.checkSession().pipe(
    map((userValidation: UserValidationI) => {
      console.log("User validation :"  + userValidation.role);
      if (userValidation.is_valid && userValidation.role == 'admin') {
        return true;
      } else {
        router.navigate(['/dashboard']);
        return false;
      }
    })
  );
};
