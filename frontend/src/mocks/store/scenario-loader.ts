import { SCENARIOS } from '../fixtures/scenarios';
import { mockStore } from './mock-store';

export function loadScenarioFromUrl(): void {
  if (typeof window === 'undefined') return;
  const name = new URLSearchParams(window.location.search).get('state');
  if (!name) return;
  const factory = SCENARIOS[name];
  if (!factory) {
    console.warn(`[mock] unknown scenario "${name}". Available:`, Object.keys(SCENARIOS));
    return;
  }
  mockStore.loadScenario(factory(), name);
}
