import {
  ChangeDetectionStrategy,
  Component,
  HostListener,
  computed,
  inject,
  signal,
} from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { Router } from '@angular/router';
import { ChatbotStatus } from '../../app/interfaces/chatbot-i';
import { AuthService } from '../../app/services/core/auth.service';
import { MockAuthService } from '../services/mock-auth.service';
import { mockStore } from '../store/mock-store';
import { SCENARIOS } from '../fixtures/scenarios';
import { panelState } from './mock-dev-panel.state';

type Tab = 'scenario' | 'chatbot' | 'features' | 'timing' | 'share' | 'auth';

@Component({
  selector: 'mock-dev-panel',
  standalone: true,
  imports: [CommonModule, FormsModule],
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './mock-dev-panel.component.html',
  styleUrls: ['./mock-dev-panel.component.scss'],
})
export class MockDevPanelComponent {
  private router = inject(Router);
  private authService = inject(AuthService) as unknown as MockAuthService;

  readonly scenarios = Object.keys(SCENARIOS);
  readonly statusOptions: ChatbotStatus[] = [
    ChatbotStatus.READY,
    ChatbotStatus.PROCESSING,
    ChatbotStatus.ERROR,
  ];

  readonly panelState = panelState;
  readonly mockStore = mockStore;

  readonly activeTab = signal<Tab>('scenario');
  readonly adminMode = signal<boolean>(false);
  readonly copied = signal<boolean>(false);

  readonly chatbots = computed(() => mockStore.chatbots());
  readonly selectedState = computed(() => {
    const id = panelState.selectedChatbotId() ?? this.chatbots()[0]?.chatbot.id;
    return this.chatbots().find((s) => s.chatbot.id === id);
  });

  @HostListener('window:keydown', ['$event'])
  onKeydown(ev: KeyboardEvent): void {
    if (ev.ctrlKey && ev.shiftKey && ev.key.toLowerCase() === 'm') {
      ev.preventDefault();
      panelState.collapsed.update((v) => !v);
    }
  }

  selectTab(tab: Tab): void {
    this.activeTab.set(tab);
  }

  toggleCollapsed(): void {
    panelState.collapsed.update((v) => !v);
  }

  onScenarioChange(name: string): void {
    const factory = SCENARIOS[name];
    if (!factory) return;
    // Force fresh seed instead of localStorage restore on reload.
    try {
      localStorage.removeItem(`mockStore:snapshot:${name}`);
    } catch {
      /* ignore */
    }
    const firstId = factory()[0]?.chatbot.id ?? null;
    const path = firstId ? `/dashboard/edit/${firstId}` : '/dashboard';
    window.location.href = `${path}?state=${encodeURIComponent(name)}`;
  }

  openSelectedInEditor(): void {
    const id = this.selectedState()?.chatbot.id;
    if (!id) return;
    this.router.navigate(['/dashboard/edit', id]);
  }

  resetStore(): void {
    try {
      const scenario = panelState.scenario();
      localStorage.removeItem(
        `mockStore:snapshot:${scenario ?? '_default'}`
      );
      localStorage.removeItem('mockStore:currentScenario');
    } catch {
      /* ignore */
    }
    window.location.href = '/dashboard';
  }

  onSelectedChatbotChange(id: string): void {
    panelState.selectedChatbotId.set(id);
  }

  onStatusChange(status: ChatbotStatus): void {
    const id = this.selectedState()?.chatbot.id;
    if (!id) return;
    if (status === ChatbotStatus.PROCESSING) {
      mockStore.beginReindex(id);
    } else {
      mockStore.stopTickLoop();
      mockStore.setStatus(id, status);
    }
  }

  onProgressChange(value: number): void {
    const state = this.selectedState();
    if (!state) return;
    mockStore.autoAdvance.set(false);
    mockStore.stopTickLoop();
    mockStore.setJobProgress(state.chatbot.id, value, state.jobProgress.total || state.files.length || 1);
  }

  tickOnce(): void {
    mockStore.tickOnce();
  }

  onAutoAdvanceChange(enabled: boolean): void {
    mockStore.autoAdvance.set(enabled);
    if (enabled) mockStore.startTickLoop();
    else mockStore.stopTickLoop();
  }

  onFeatureToggle(key: 'cite_sources' | 'force_ocr', value: boolean): void {
    const state = this.selectedState();
    if (!state) return;
    mockStore.updateChatbot(state.chatbot.id, { [key]: value });
  }

  onAccessLevelChange(value: 'public' | 'private' | 'password'): void {
    const state = this.selectedState();
    if (!state) return;
    mockStore.updateChatbot(state.chatbot.id, { access_level: value });
  }

  injectErrorOnFirstFile(): void {
    const state = this.selectedState();
    if (!state || state.files.length === 0) return;
    mockStore.injectFileError(state.chatbot.id, state.files[0]!.id);
  }

  async copyShareUrl(): Promise<void> {
    const params = new URLSearchParams(window.location.search);
    const scenario = panelState.scenario();
    if (scenario) params.set('state', scenario);
    else params.delete('state');
    const url = `${window.location.origin}${window.location.pathname}?${params.toString()}`;
    try {
      await navigator.clipboard.writeText(url);
      this.copied.set(true);
      setTimeout(() => this.copied.set(false), 1500);
    } catch {
      /* clipboard not available */
    }
  }

  onAdminToggle(value: boolean): void {
    this.adminMode.set(value);
    this.authService.setAdminMode(value);
  }
}
