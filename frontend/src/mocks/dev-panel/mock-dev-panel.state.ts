import { signal } from '@angular/core';

class PanelState {
  readonly collapsed = signal<boolean>(false);
  readonly scenario = signal<string | null>(null);
  readonly selectedChatbotId = signal<string | null>(null);
  readonly latencyMs = signal<number>(0);

  toQueryParams(): Record<string, string | null> {
    return {
      state: this.scenario() ?? null,
    };
  }
}

export const panelState = new PanelState();

if (typeof window !== 'undefined') {
  const sp = new URLSearchParams(window.location.search);
  const s = sp.get('state');
  if (s) panelState.scenario.set(s);
}
