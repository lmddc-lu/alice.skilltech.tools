import { ChangeDetectionStrategy, Component, inject, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { TranslateService, TranslatePipe } from '@ngx-translate/core';

@Component({
  selector: 'app-language-selector',
  standalone: true,
  imports: [TranslatePipe],
  template: `
    <div class="language-selector">
      <select
        class="language-select"
        [value]="currentLanguage()"
        (change)="changeLanguage($event)"
        [attr.aria-label]="'Select language'"
      >
        <option value="en">{{ 'languages.en' | translate }}</option>
        <option value="de">{{ 'languages.de' | translate }}</option>
        <option value="fr">{{ 'languages.fr' | translate }}</option>
        <option value="lb">{{ 'languages.lb' | translate }}</option>
      </select>
    </div>
  `,
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class LanguageSelectorComponent {
  private translate = inject(TranslateService);

  readonly currentLanguage = signal<string>(
    this.translate.getCurrentLang() || this.translate.getFallbackLang() || 'en'
  );

  constructor() {
    this.translate.onLangChange
      .pipe(takeUntilDestroyed())
      .subscribe((event) => this.currentLanguage.set(event.lang));
  }

  changeLanguage(event: Event): void {
    const target = event.target as HTMLSelectElement;
    const selectedLanguage = target.value;

    this.translate.use(selectedLanguage);
    this.currentLanguage.set(selectedLanguage);

    localStorage.setItem('selectedLanguage', selectedLanguage);
  }
}
