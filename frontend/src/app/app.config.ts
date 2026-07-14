import { ApplicationConfig, provideZoneChangeDetection } from '@angular/core';
import { provideRouter } from '@angular/router';

import { routes } from './app.routes';
import { provideHttpClient, withInterceptors } from '@angular/common/http';
import {
  provideTranslateService,
} from '@ngx-translate/core';
import { provideTranslateHttpLoader } from '@ngx-translate/http-loader';
import { authInterceptor } from './interceptors/auth.interceptor';
import { provideMarkdown, KATEX_OPTIONS, MERMAID_OPTIONS, SANITIZE } from 'ngx-markdown';
import { LOCALE_ID } from '@angular/core';
import DOMPurify from 'dompurify';

// Angular's HTML sanitizer strips inline `style` attributes, but KaTeX positions
// every glyph through inline styles (height/top/vertical-align), so the default
// sanitizer collapses formulas into overlapping text. DOMPurify keeps `style` and
// MathML while still removing scripts and event handlers.
function sanitizeMarkdownHtml(html: string): string {
  return DOMPurify.sanitize(html);
}

export const appConfig: ApplicationConfig = {
  providers: [
    provideZoneChangeDetection({ eventCoalescing: true }),
    provideRouter(routes),
    provideHttpClient(withInterceptors([authInterceptor])),
    provideTranslateService({
      loader: provideTranslateHttpLoader({
        prefix: './i18n/',
        suffix: '.json',
        enforceLoading: true
      }),
      fallbackLang: 'en',
      lang: 'en',
    }),
    provideMarkdown({
      // DOMPurify keeps KaTeX's inline styles; Angular's default sanitizer drops them.
      sanitize: {
        provide: SANITIZE,
        useValue: sanitizeMarkdownHtml,
      },
      // throwOnError:false so malformed LaTeX in model output renders as text
      // instead of breaking the whole message. nonStandard:true lets `$...$`
      // render even when it hugs punctuation like parentheses (e.g. "($h$)"),
      // which the default rule rejects because it requires surrounding whitespace.
      katexOptions: {
        provide: KATEX_OPTIONS,
        useValue: { throwOnError: false, nonStandard: true },
      },
      // startOnLoad:false because ngx-markdown drives mermaid.run() itself;
      // strict security since diagram source comes from untrusted model output.
      mermaidOptions: {
        provide: MERMAID_OPTIONS,
        useValue: { startOnLoad: false, securityLevel: 'strict' },
      },
    }),
    {provide: LOCALE_ID, useValue: 'fr-FR'}
  ],
};
