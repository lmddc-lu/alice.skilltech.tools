import {
  ChangeDetectorRef,
  OnDestroy,
  Pipe,
  PipeTransform,
  inject,
} from '@angular/core';
import { TranslateService } from '@ngx-translate/core';
import { Subscription } from 'rxjs';
import { parseMlang } from './mlang';

@Pipe({ name: 'mlang', pure: false, standalone: true })
export class MlangPipe implements PipeTransform, OnDestroy {
  private translate = inject(TranslateService);
  private ref = inject(ChangeDetectorRef);
  private sub?: Subscription;
  private lastValue = '';
  private lastInput: string | null | undefined = undefined;
  private lastLang = '';

  transform(value: string | null | undefined): string {
    this.ensureSubscribed();
    const lang =
      this.translate.getCurrentLang() ||
      this.translate.getFallbackLang() ||
      'en';
    if (value === this.lastInput && lang === this.lastLang) {
      return this.lastValue;
    }
    this.lastInput = value;
    this.lastLang = lang;
    this.lastValue = parseMlang(value, lang);
    return this.lastValue;
  }

  ngOnDestroy(): void {
    this.sub?.unsubscribe();
  }

  private ensureSubscribed(): void {
    if (this.sub) return;
    this.sub = this.translate.onLangChange.subscribe(() => {
      this.lastLang = '';
      this.ref.markForCheck();
    });
  }
}
