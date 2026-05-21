import {
  Component,
  ChangeDetectionStrategy,
  signal,
  input,
  output,
  inject,
  effect,
} from '@angular/core';
import { TranslatePipe } from '@ngx-translate/core';
import { ChatbotService } from '../../../../services/chatbot/chatbot.service';
import { ChatbotFile } from '../../../../interfaces/chatbot-i';
import { ContentBrowserComponent, TreeNode, PreviewState } from '../content-browser/content-browser.component';

@Component({
  selector: 'app-file-content-browser',
  imports: [ContentBrowserComponent, TranslatePipe],
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './file-content-browser.component.html',
})
export class FileContentBrowserComponent {
  private chatbotService = inject(ChatbotService);

  chatbotId = input.required<string>();
  isOpen = input<boolean>(false);
  files = input<ChatbotFile[]>([]);

  close = output<void>();

  treeNodes = signal<TreeNode[]>([]);
  preview = signal<PreviewState>({ type: 'idle' });

  constructor() {
    effect(() => {
      if (this.isOpen()) {
        this.initTree();
      }
    });
  }

  initTree(): void {
    const files = this.files().filter((f) => f.status === 'uploaded');
    this.treeNodes.set(
      files.map((file) => ({
        name: file.filename,
        value: `file:${file.id}`,
        icon: this.getFileIcon(file.mime_type),
        type: 'file',
        meta: this.formatFileSize(file.size),
        data: { fileId: file.id },
      }))
    );
    this.preview.set({ type: 'idle' });
  }

  onNodeClick(node: TreeNode): void {
    if (node.type === 'file') {
      this.loadFileContent(node);
    }
  }

  private loadFileContent(node: TreeNode): void {
    const fileId = node.data?.['fileId'] as string;
    this.preview.set({ type: 'loading', fileName: node.name });

    const externalUrl = this.chatbotService.getFileDownloadPath(
      this.chatbotId(),
      fileId
    );

    this.chatbotService
      .getFileParsedContent(this.chatbotId(), fileId)
      .subscribe({
        next: (result) => {
          this.preview.set({
            type: 'content',
            fileName: node.name,
            content: result.content,
            totalChunks: result.total_chunks,
            externalUrl,
          });
        },
        error: (err) => {
          if (err.status === 404) {
            this.preview.set({ type: 'no-content', fileName: node.name });
          } else {
            this.preview.set({ type: 'error', fileName: node.name });
          }
        },
      });
  }

  private getFileIcon(mimeType: string): string {
    if (!mimeType) return '/icons/file.svg';
    if (mimeType.includes('pdf')) return '/icons/file.svg';
    if (mimeType.includes('presentation') || mimeType.includes('powerpoint'))
      return '/icons/monitor.svg';
    if (mimeType.includes('spreadsheet') || mimeType.includes('excel'))
      return '/icons/grid.svg';
    if (mimeType.includes('word') || mimeType.includes('document'))
      return '/icons/file.svg';
    if (mimeType.startsWith('image/')) return '/icons/eye.svg';
    if (mimeType.includes('text') || mimeType.includes('markdown'))
      return '/icons/file.svg';
    return '/icons/file.svg';
  }

  private formatFileSize(bytes: number): string {
    if (bytes === 0) return '0 B';
    const k = 1024;
    const sizes = ['B', 'KB', 'MB', 'GB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return parseFloat((bytes / Math.pow(k, i)).toFixed(1)) + ' ' + sizes[i];
  }
}
