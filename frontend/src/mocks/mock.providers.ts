import { Provider, Type } from '@angular/core';
import { AuthService } from '../app/services/core/auth.service';
import { DEV_PANEL_COMPONENT } from '../app/core/dev-panel.token';
import { MockAuthService } from './services/mock-auth.service';
import { MockDevPanelComponent } from './dev-panel/mock-dev-panel.component';

export const MOCK_PROVIDERS: Provider[] = [
  { provide: AuthService, useClass: MockAuthService },
  { provide: DEV_PANEL_COMPONENT, useValue: MockDevPanelComponent as Type<unknown> },
];
