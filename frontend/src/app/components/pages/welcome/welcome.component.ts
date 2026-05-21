import { AfterViewInit, ChangeDetectionStrategy, Component, inject } from '@angular/core';
import { AuthService } from '../../../services/core/auth.service';
import { TranslatePipe } from '@ngx-translate/core';
import { LanguageSelectorComponent } from '../../shared/components/language-selector/language-selector.component';
import { Router } from '@angular/router';

@Component({
  selector: 'app-welcome',
  imports: [TranslatePipe, LanguageSelectorComponent],
  templateUrl: './welcome.component.html',
  styleUrl: './welcome.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class WelcomeComponent implements AfterViewInit {
  private auth = inject(AuthService);
  private router = inject(Router);

  ngAfterViewInit(): void {
    if (this.auth.isAuthenticated()) {
      const returnUrl = sessionStorage.getItem('returnUrl');
      if (returnUrl) {
        sessionStorage.removeItem('returnUrl');
        this.router.navigateByUrl(returnUrl);
      } else {
        this.router.navigate(['/dashboard']);
      }
    } else {
      setTimeout(() => {
        this.login();
      }, 100);
    }
  }

  login(): void {
    this.auth.login();
  }
}
