import { ChangeDetectionStrategy, Component, Type, inject } from '@angular/core';
import { NgComponentOutlet } from '@angular/common';
import { RouterOutlet } from '@angular/router';
import { TranslateService } from '@ngx-translate/core';
import { DEV_PANEL_COMPONENT } from './core/dev-panel.token';

@Component({
  selector: 'app-root',
  templateUrl: './app.component.html',
  styleUrl: './app.component.scss',
  standalone: true,
  imports: [NgComponentOutlet, RouterOutlet],
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class AppComponent {
  title = 'frontend';
  readonly devPanel: Type<unknown> | null = inject(DEV_PANEL_COMPONENT, { optional: true });
  private translate = inject(TranslateService);

  constructor() {
    this.initializeLanguage();
  }

  private initializeLanguage(): void {
    const supportedLanguages = ['de', 'en', 'fr', 'lb'];
    const fallbackLanguage = 'en';

    const savedLanguage = localStorage.getItem('selectedLanguage');

    this.translate.addLangs(supportedLanguages);
    this.translate.setFallbackLang(fallbackLanguage);

    if (savedLanguage && supportedLanguages.includes(savedLanguage)) {
      this.translate.use(savedLanguage);
    } else {
      this.translate.use('fr');
      localStorage.setItem('selectedLanguage', 'fr');
    }
  }
}
