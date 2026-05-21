import {
  Component,
  ChangeDetectionStrategy,
  signal,
  computed,
  input,
  output,
  inject,
  effect,
} from '@angular/core';

import { TranslatePipe } from '@ngx-translate/core';
import { ChatbotService } from '../../../../services/chatbot/chatbot.service';
import { ChatbotFile } from '../../../../interfaces/chatbot-i';
import {
  TextEntryDialogComponent,
  TextEntrySaveEvent,
} from '../text-entry-dialog/text-entry-dialog.component';

interface FileUploadProgress {
  file: File;
  progress: number;
  status: 'pending' | 'uploading' | 'completed' | 'error';
  error?: string;
}

interface StagedFile {
  id: string;
  file: File;
  name: string;
  size: number;
  type: string;
}

interface StagedTextEntry {
  id: string;
  title: string;
  content: string;
  // When set, the staged edit atomically replaces an existing free-text
  // file on the server on save.
  replaceFileId?: string;
  replaceFilename?: string;
}

@Component({
  selector: 'app-file-manager-modal',
  imports: [TranslatePipe, TextEntryDialogComponent],
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './file-manager-modal.component.html',
  styleUrl: './file-manager-modal.component.scss',
})
export class FileManagerModalComponent {
  private chatbotService = inject(ChatbotService);

  chatbotId = input.required<string>();
  isOpen = input<boolean>(false);
  initialFiles = input<ChatbotFile[]>([]);

  close = output<void>();
  saved = output<void>();

  loading = signal(false);
  files = signal<ChatbotFile[]>([]);
  uploadingFiles = signal<FileUploadProgress[]>([]);
  stagedFiles = signal<StagedFile[]>([]);
  stagedTextEntries = signal<StagedTextEntry[]>([]);
  filesToDelete = signal<Set<string>>(new Set());
  newlyUploadedFiles = signal<Set<string>>(new Set());
  isUploading = signal(false);
  isDraggingFiles = signal(false);
  showConfirmChanges = signal(false);

  textDialogOpen = signal(false);
  textDialogMode = signal<'create' | 'edit'>('create');
  textDialogLoading = signal(false);
  textDialogInitialTitle = signal('');
  textDialogInitialContent = signal('');
  textDialogResetToken = signal(0);
  // null when creating; a staged entry id when re-editing a stage; a
  // server file id when editing a persisted free-text file.
  editingStagedTextId = signal<string | null>(null);
  editingServerFileId = signal<string | null>(null);

  totalFilesSize = computed(() => {
    return this.files().reduce((sum, file) => sum + file.size, 0);
  });

  hasChanges = computed(() => {
    return (
      this.stagedFiles().length > 0 ||
      this.stagedTextEntries().length > 0 ||
      this.filesToDelete().size > 0
    );
  });

  // Existing server files replaced by a staged text edit - hidden from
  // the list so the user sees a single row per entry.
  private replacedFileIds = computed(
    () =>
      new Set(
        this.stagedTextEntries()
          .map((t) => t.replaceFileId)
          .filter((id): id is string => !!id)
      )
  );

  displayedFiles = computed(() => {
    const replacedIds = this.replacedFileIds();
    const existingFiles = this.files().filter((f) => !replacedIds.has(f.id));

    const stagedAsFiles: ChatbotFile[] = this.stagedFiles().map((staged) => ({
      id: staged.id,
      filename: staged.name,
      mime_type: staged.type,
      size: staged.size,
      upload_date: new Date().toISOString(),
      status: 'processing' as const,
      is_free_text: false,
      ingestion_state: null,
      ingestion_error: null,
      ingestion_error_code: null,
    }));

    // Use status 'uploaded' so the template renders the normal action
    // row (pencil/trash) for these staged-but-not-yet-saved entries.
    const stagedTextAsFiles: ChatbotFile[] = this.stagedTextEntries().map(
      (entry) => ({
        id: entry.id,
        filename: entry.title || 'Untitled',
        mime_type: 'text/plain',
        size: entry.content.length,
        upload_date: new Date().toISOString(),
        status: 'uploaded' as const,
        is_free_text: true,
        ingestion_state: null,
        ingestion_error: null,
        ingestion_error_code: null,
      })
    );

    return [...stagedTextAsFiles, ...stagedAsFiles, ...existingFiles];
  });

  failedFiles = computed(() =>
    this.files().filter((f) => f.ingestion_state === 'failed')
  );
  hasFailedFiles = computed(() => this.failedFiles().length > 0);

  stagedFileIds = computed(() => {
    return new Set(this.stagedFiles().map((f) => f.id));
  });

  stagedTextEntryIds = computed(() => {
    return new Set(this.stagedTextEntries().map((t) => t.id));
  });

  filesToDeleteList = computed(() => {
    const deletedIds = this.filesToDelete();
    return this.files().filter((file) => deletedIds.has(file.id));
  });

  resultingFiles = computed(() => {
    const deletedIds = this.filesToDelete();
    const replacedIds = this.replacedFileIds();
    const existingFiles = this.files().filter(
      (file) =>
        !deletedIds.has(file.id) &&
        !replacedIds.has(file.id) &&
        file.status === 'uploaded'
    );

    const stagedAsFiles: ChatbotFile[] = this.stagedFiles().map((staged) => ({
      id: staged.id,
      filename: staged.name,
      mime_type: staged.type,
      size: staged.size,
      upload_date: new Date().toISOString(),
      status: 'uploaded' as const,
      is_free_text: false,
      ingestion_state: null,
      ingestion_error: null,
      ingestion_error_code: null,
    }));

    const stagedTextAsFiles: ChatbotFile[] = this.stagedTextEntries().map(
      (entry) => ({
        id: entry.id,
        filename: entry.title || 'Untitled',
        mime_type: 'text/plain',
        size: entry.content.length,
        upload_date: new Date().toISOString(),
        status: 'uploaded' as const,
        is_free_text: true,
        ingestion_state: null,
        ingestion_error: null,
        ingestion_error_code: null,
      })
    );

    return [...stagedTextAsFiles, ...stagedAsFiles, ...existingFiles];
  });

  constructor() {
    effect(() => {
      if (this.isOpen()) {
        this.files.set(this.initialFiles());
        this.showConfirmChanges.set(false);
        this.stagedFiles.set([]);
        this.stagedTextEntries.set([]);
        this.filesToDelete.set(new Set());
      }
    });
  }

  onOverlayClick(event: MouseEvent): void {
    if (event.target === event.currentTarget) {
      this.closeModal();
    }
  }

  closeModal(): void {
    this.showConfirmChanges.set(false);
    this.uploadingFiles.set([]);
    this.stagedFiles.set([]);
    this.stagedTextEntries.set([]);
    this.filesToDelete.set(new Set());
    this.newlyUploadedFiles.set(new Set());
    this.close.emit();
  }

  onFilesDragOver(event: DragEvent): void {
    event.preventDefault();
    event.stopPropagation();
    this.isDraggingFiles.set(true);
  }

  onFilesDragLeave(event: DragEvent): void {
    event.preventDefault();
    event.stopPropagation();
    this.isDraggingFiles.set(false);
  }

  onFilesDrop(event: DragEvent): void {
    event.preventDefault();
    event.stopPropagation();
    this.isDraggingFiles.set(false);

    const droppedFiles = event.dataTransfer?.files;
    if (droppedFiles) {
      this.handleFileSelection(Array.from(droppedFiles));
    }
  }

  onFilesSelected(event: Event): void {
    const input = event.target as HTMLInputElement;
    if (input.files) {
      this.handleFileSelection(Array.from(input.files));
      input.value = '';
    }
  }

  private handleFileSelection(selectedFiles: File[]): void {
    const validFiles = selectedFiles.filter((file) => {
      const validTypes = [
        'application/pdf',
        'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
        'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        'application/vnd.openxmlformats-officedocument.presentationml.presentation',
        'text/plain',
        'text/markdown',
        'text/html',
        'text/csv',
        'application/x-latex',
        'text/x-tex',
        'image/png',
        'image/jpeg',
        'image/tiff',
        'image/bmp',
        'image/webp',
      ];
      // H5P files are zip archives, so browsers report empty/generic
      // MIME types - accept them by extension instead.
      const validExtensions = ['.h5p'];
      const maxSize = 100 * 1024 * 1024;

      const lowerName = file.name.toLowerCase();
      const hasValidExtension = validExtensions.some((ext) =>
        lowerName.endsWith(ext),
      );

      if (!hasValidExtension && !validTypes.includes(file.type)) {
        console.warn(`Invalid file type: ${file.type}`);
        return false;
      }

      if (file.size > maxSize) {
        console.warn(`File too large: ${file.name}`);
        return false;
      }

      return true;
    });

    if (validFiles.length === 0) return;

    this.stageFiles(validFiles);
  }

  private stageFiles(filesToStage: File[]): void {
    const newStagedFiles: StagedFile[] = filesToStage.map((file) => ({
      id: `staged-${Date.now()}-${Math.random()}`,
      file,
      name: file.name,
      size: file.size,
      type: file.type,
    }));

    this.stagedFiles.update((currentFiles) => [
      ...currentFiles,
      ...newStagedFiles,
    ]);
  }

  removeStagedFile(fileId: string): void {
    this.stagedFiles.update((currentFiles) =>
      currentFiles.filter((f) => f.id !== fileId)
    );
  }

  removeStagedTextEntry(entryId: string): void {
    this.stagedTextEntries.update((entries) =>
      entries.filter((e) => e.id !== entryId)
    );
  }

  markFileForDeletion(fileId: string): void {
    const stagedFile = this.stagedFiles().find((f) => f.id === fileId);
    if (stagedFile) {
      this.removeStagedFile(fileId);
      return;
    }

    const stagedText = this.stagedTextEntries().find((t) => t.id === fileId);
    if (stagedText) {
      // Discarding the stage leaves the original server file untouched
      // since the replace was never committed.
      this.removeStagedTextEntry(fileId);
      return;
    }

    const file = this.files().find((f) => f.id === fileId);
    if (file?.status === 'processing') return;

    this.filesToDelete.update((ids) => {
      const newSet = new Set(ids);
      if (newSet.has(fileId)) {
        newSet.delete(fileId);
      } else {
        newSet.add(fileId);
      }
      return newSet;
    });
  }

  proceedToConfirm(): void {
    if (!this.hasChanges()) return;
    this.showConfirmChanges.set(true);
  }

  backToFileManagement(): void {
    this.showConfirmChanges.set(false);
  }

  async confirmChanges(): Promise<void> {
    const chatbotId = this.chatbotId();
    if (!chatbotId) return;

    this.isUploading.set(true);

    try {
      const filesToAdd = this.stagedFiles().map((sf) => sf.file);
      const textEntries = this.stagedTextEntries().map((t) => ({
        title: t.title,
        content: t.content,
        ...(t.replaceFileId ? { file_id_to_replace: t.replaceFileId } : {}),
      }));
      const fileIdsToDelete = Array.from(this.filesToDelete());

      await new Promise<void>((resolve, reject) => {
        this.chatbotService
          .updateFiles(chatbotId, filesToAdd, fileIdsToDelete, textEntries)
          .subscribe({
            next: (result) => {
              console.log('Files updated successfully:', result);
              resolve();
            },
            error: (err) => {
              console.error('Error updating files:', err);
              reject(err);
            },
          });
      });

      this.stagedFiles.set([]);
      this.stagedTextEntries.set([]);
      this.filesToDelete.set(new Set());
      this.newlyUploadedFiles.set(new Set());
      this.uploadingFiles.set([]);
      this.showConfirmChanges.set(false);
      this.isUploading.set(false);

      this.saved.emit();
      this.close.emit();
    } catch {
      alert('Failed to save changes. Please try again.');
      this.isUploading.set(false);
    }
  }

  openFile(file: ChatbotFile): void {
    const chatbotId = this.chatbotId();
    if (!chatbotId || !file.id) return;

    const url = this.chatbotService.getFileDownloadPath(chatbotId, file.id);
    window.open(url, '_blank');
  }

  openCreateTextDialog(): void {
    this.editingStagedTextId.set(null);
    this.editingServerFileId.set(null);
    this.textDialogMode.set('create');
    this.textDialogInitialTitle.set('');
    this.textDialogInitialContent.set('');
    this.textDialogLoading.set(false);
    this.textDialogResetToken.update((v) => v + 1);
    this.textDialogOpen.set(true);
  }

  openEditTextDialog(file: ChatbotFile): void {
    const chatbotId = this.chatbotId();
    if (!chatbotId || !file.id) return;

    // Re-editing a not-yet-saved staged entry: reopen the dialog from
    // the staged values, no API call.
    const existingStaged = this.stagedTextEntries().find(
      (t) => t.id === file.id
    );
    if (existingStaged) {
      this.editingStagedTextId.set(existingStaged.id);
      this.editingServerFileId.set(existingStaged.replaceFileId ?? null);
      this.textDialogMode.set('edit');
      this.textDialogInitialTitle.set(existingStaged.title);
      this.textDialogInitialContent.set(existingStaged.content);
      this.textDialogLoading.set(false);
      this.textDialogResetToken.update((v) => v + 1);
      this.textDialogOpen.set(true);
      return;
    }

    // Editing a persisted free-text file: fetch current content, then
    // stage the change. The fetch loads only; nothing is committed until
    // save.
    this.editingStagedTextId.set(null);
    this.editingServerFileId.set(file.id);
    this.textDialogMode.set('edit');
    this.textDialogInitialTitle.set('');
    this.textDialogInitialContent.set('');
    this.textDialogLoading.set(true);
    this.textDialogResetToken.update((v) => v + 1);
    this.textDialogOpen.set(true);

    this.chatbotService.getTextEntry(chatbotId, file.id).subscribe({
      next: (res) => {
        this.textDialogInitialTitle.set(res.title);
        this.textDialogInitialContent.set(res.content);
        this.textDialogResetToken.update((v) => v + 1);
        this.textDialogLoading.set(false);
      },
      error: (err) => {
        console.error('Failed to load text entry:', err);
        this.textDialogLoading.set(false);
        this.textDialogOpen.set(false);
        alert('Failed to load text content. Please try again.');
      },
    });
  }

  closeTextDialog(): void {
    this.textDialogOpen.set(false);
    this.editingStagedTextId.set(null);
    this.editingServerFileId.set(null);
  }

  onTextDialogSave(event: TextEntrySaveEvent): void {
    const stagedId = this.editingStagedTextId();
    const replaceFileId = this.editingServerFileId();
    const replaceFilename = replaceFileId
      ? this.files().find((f) => f.id === replaceFileId)?.filename
      : undefined;

    if (stagedId) {
      this.stagedTextEntries.update((entries) =>
        entries.map((e) =>
          e.id === stagedId
            ? { ...e, title: event.title, content: event.content }
            : e
        )
      );
    } else {
      const newEntry: StagedTextEntry = {
        id: `staged-text-${Date.now()}-${Math.random()}`,
        title: event.title,
        content: event.content,
        replaceFileId: replaceFileId ?? undefined,
        replaceFilename,
      };
      this.stagedTextEntries.update((entries) => [...entries, newEntry]);
    }

    this.textDialogOpen.set(false);
    this.editingStagedTextId.set(null);
    this.editingServerFileId.set(null);
  }

  formatFileSize(bytes: number): string {
    if (bytes === 0) return '0 Bytes';
    const k = 1024;
    const sizes = ['Bytes', 'KB', 'MB', 'GB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return Math.round((bytes / Math.pow(k, i)) * 100) / 100 + ' ' + sizes[i];
  }

  getFileIcon(mimeType: string): string {
    if (!mimeType) {
      return '/icons/file.svg';
    }
    if (mimeType.includes('pdf')) return '/icons/file.svg';
    if (mimeType.includes('word')) return '/icons/file.svg';
    if (mimeType.includes('powerpoint') || mimeType.includes('presentation'))
      return '/icons/monitor.svg';
    return '/icons/file.svg';
  }
}
