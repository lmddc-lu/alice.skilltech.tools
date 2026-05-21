import { bootstrapApplication } from '@angular/platform-browser';
import { appConfig } from './app/app.config';
import { AppComponent } from './app/app.component';
import { worker } from './mocks/browser';
import { MOCK_PROVIDERS } from './mocks/mock.providers';

async function bootstrap() {
  await worker.start({
    onUnhandledRequest: 'warn',
    serviceWorker: { url: '/mockServiceWorker.js' },
  });
  const { loadScenarioFromUrl } = await import('./mocks/store/scenario-loader');
  loadScenarioFromUrl();
  return bootstrapApplication(AppComponent, {
    ...appConfig,
    providers: [...(appConfig.providers ?? []), ...MOCK_PROVIDERS],
  });
}

bootstrap().catch((err) => console.error(err));
