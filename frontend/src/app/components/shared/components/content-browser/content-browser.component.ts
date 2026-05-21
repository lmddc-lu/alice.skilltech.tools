import {
  Component,
  ChangeDetectionStrategy,
  signal,
  input,
  output,
  computed,
} from '@angular/core';
import { NgTemplateOutlet } from '@angular/common';
import { Tree, TreeItem, TreeItemGroup } from '@angular/aria/tree';
import { TranslatePipe } from '@ngx-translate/core';

export type TreeNode = {
  name: string;
  value: string;
  icon: string;
  type: string;
  meta?: string;
  children?: TreeNode[];
  expanded?: boolean;
  data?: Record<string, unknown>;
};

export type PreviewState =
  | { type: 'idle' }
  | { type: 'loading'; fileName: string }
  | { type: 'content'; fileName: string; content: string; totalChunks: number; externalUrl?: string | null }
  | { type: 'error'; fileName: string }
  | { type: 'no-content'; fileName: string };

@Component({
  selector: 'app-content-browser',
  imports: [TranslatePipe, NgTemplateOutlet, Tree, TreeItem, TreeItemGroup],
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './content-browser.component.html',
  styleUrl: './content-browser.component.scss',
})
export class ContentBrowserComponent {
  isOpen = input<boolean>(false);
  title = input.required<string>();
  treeNodes = input<TreeNode[]>([]);
  preview = input<PreviewState>({ type: 'idle' });
  loadingStructure = input<boolean>(false);
  emptyIcon = input<string>('/icons/file.svg');
  emptyText = input.required<string>();

  close = output<void>();
  nodeClick = output<TreeNode>();

  selectedValue = signal<string[]>([]);

  previewLoading = computed(() => this.preview().type === 'loading');
  previewError = computed(() => this.preview().type === 'error');
  previewNoContent = computed(() => this.preview().type === 'no-content');

  previewContent = computed(() => {
    const p = this.preview();
    return p.type === 'content' ? p.content : null;
  });

  previewFileName = computed(() => {
    const p = this.preview();
    return p.type === 'idle' ? '' : p.fileName;
  });

  previewTotalChunks = computed(() => {
    const p = this.preview();
    return p.type === 'content' ? p.totalChunks : 0;
  });

  previewExternalUrl = computed(() => {
    const p = this.preview();
    return p.type === 'content' ? (p.externalUrl ?? null) : null;
  });

  onOverlayClick(event: MouseEvent): void {
    if (event.target === event.currentTarget) {
      this.close.emit();
    }
  }

  onNodeSelect(node: TreeNode): void {
    this.nodeClick.emit(node);
  }

  openExternal(): void {
    const url = this.previewExternalUrl();
    if (url) window.open(url, '_blank');
  }
}
