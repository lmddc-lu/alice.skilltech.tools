import { ApplicationConfig, provideZoneChangeDetection } from '@angular/core';
import { provideRouter } from '@angular/router';

import { routes } from './app.routes';
import { provideHttpClient, withFetch, withInterceptors } from '@angular/common/http';
import {
  provideTranslateService,
} from '@ngx-translate/core';
import { provideTranslateHttpLoader } from '@ngx-translate/http-loader';
import { authInterceptor } from './interceptors/auth.interceptor';
import { provideMarkdown } from 'ngx-markdown';
import { LOCALE_ID } from '@angular/core';

export const appConfig: ApplicationConfig = {
  providers: [
    provideZoneChangeDetection({ eventCoalescing: true }),
    provideRouter(routes),
    provideHttpClient(withFetch(), withInterceptors([authInterceptor])),
    provideTranslateService({
      loader: provideTranslateHttpLoader({
        prefix: './i18n/',
        suffix: '.json',
        enforceLoading: true
      }),
      fallbackLang: 'en',
      lang: 'en',
    }),
    provideMarkdown(),
    {provide: LOCALE_ID, useValue: 'fr-FR'}
  ],
};
