import { ChangeDetectionStrategy, Component, inject } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { LanguageSelectorComponent } from '../../components/language-selector/language-selector.component';
import { AuthService } from '../../../../services/core/auth.service';
import { RouterLink } from '@angular/router';

@Component({
  selector: 'app-header',
  imports: [LanguageSelectorComponent, RouterLink],
  templateUrl: './header.component.html',
  styleUrl: './header.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class HeaderComponent {
  private authService = inject(AuthService);

  readonly userinfo = this.authService.userInfo;

  constructor() {
    this.authService.getUserInfo().pipe(takeUntilDestroyed()).subscribe();
  }

  logout(): void {
    this.authService.logout();
  }
}
