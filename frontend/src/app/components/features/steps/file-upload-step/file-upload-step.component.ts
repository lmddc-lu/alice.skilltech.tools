import {
  Component,
  input,
  output,
  signal,
  computed,
  OnInit,
  ChangeDetectionStrategy,
} from '@angular/core';

import { FormsModule } from '@angular/forms';
import { TranslatePipe } from '@ngx-translate/core';
import {
  WizardData,
  UploadedFileInfo,
  WizardTextEntry,
} from '../../new-chatbot/new-chatbot.component';
import {
  TextEntryDialogComponent,
  TextEntrySaveEvent,
} from '../../../shared/components/text-entry-dialog/text-entry-dialog.component';

@Component({
  selector: 'app-file-upload-step',
  template: `
    <div class="step-container additional">
      <div class="upload-section">
        <p class="section-description">
          @if (isMoodleAdditionalFiles()) {
          <strong>{{ 'newChatbot.fileUpload.optional' | translate }}</strong>
          {{ 'newChatbot.fileUpload.supplementMoodle' | translate }}
          } @else {
          {{ 'newChatbot.fileUpload.description' | translate }}
          }
        </p>

        <div
          class="upload-zone"
          [class.dragging]="isDragging()"
          (dragover)="onDragOver($event)"
          (dragleave)="onDragLeave($event)"
          (drop)="onDrop($event)"
          (click)="fileInput.click()"
        >
          <div class="upload-icon">
            <img
              src="/icons/icon_upload2.svg"
              alt="Upload"
              width="48"
              height="48"
            />
          </div>
          <p class="upload-text">
            <strong>{{
              'newChatbot.fileUpload.clickToUpload' | translate
            }}</strong
            ><br />
            <strong>
              {{ 'newChatbot.fileUpload.dragAndDrop' | translate }}
            </strong>
          </p>
          <p class="upload-hint">
            {{ 'newChatbot.fileUpload.supportedFormats' | translate }}
          </p>
          <input
            #fileInput
            type="file"
            multiple
            accept=".pdf,.docx,.xlsx,.pptx,.txt,.md,.html,.csv,.tex,.png,.jpg,.jpeg,.tiff,.bmp,.webp,.h5p"
            (change)="onFileSelect($event)"
            style="display: none;"
          />
        </div>

        <div class="add-text-row">
          <button
            type="button"
            class="btn btn-secondary"
            (click)="openCreateTextDialog()"
          >
            <img src="/icons/file.svg" alt="" width="16" height="16" aria-hidden="true" />
            {{ 'textEntry.addButton' | translate }}
          </button>
        </div>

        @if (textDialogOpen()) {
          <app-text-entry-dialog
            [mode]="textDialogMode()"
            [initialTitle]="textDialogInitialTitle()"
            [initialContent]="textDialogInitialContent()"
            [resetToken]="textDialogResetToken()"
            (close)="closeTextDialog()"
            (save)="onTextDialogSave($event)"
          />
        }

        <label class="force-ocr-option">
          <input
            type="checkbox"
            [checked]="data().forceOcr"
            (change)="onForceOcrChange($any($event.target).checked)"
          />
          <span class="force-ocr-label">{{ 'editChatbot.forceOcr' | translate }}</span>
          <span class="info-tooltip">
            <img src="/icons/info.svg" alt="Info" width="14" height="14" />
            <span class="tooltip-text">{{ 'editChatbot.forceOcrHint' | translate }}</span>
          </span>
        </label>

        @if (uploadedFiles().length > 0 || textEntries().length > 0) {
        <div class="files-section">
          <div class="files-header">
            <h4>
              {{ 'newChatbot.fileUpload.uploadedFiles' | translate }} ({{
                uploadedFiles().length + textEntries().length
              }})
            </h4>
            <button
              class="btn btn-ghost btn-sm"
              (click)="clearAll()"
              type="button"
            >
              <img src="/icons/trash.svg" alt="Clear" width="16" height="16" />
              {{ 'newChatbot.fileUpload.clearAll' | translate }}
            </button>
          </div>

          <div class="files-list">
            @for (entry of textEntries(); track entry.id) {
            <div class="file-item status-completed">
              <div class="file-icon">
                <img src="/icons/file.svg" alt="Text" width="24" height="24" />
              </div>
              <div class="file-info">
                <span class="file-name">
                  {{ entry.title || ('textEntry.untitled' | translate) }}
                </span>
                <span class="file-size">{{ entry.content.length }} chars</span>
              </div>
              <button
                type="button"
                class="btn-icon"
                (click)="openEditTextDialog(entry)"
                [attr.aria-label]="'textEntry.editButton' | translate"
              >
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                  <path d="M12 20h9"/>
                  <path d="M16.5 3.5a2.121 2.121 0 0 1 3 3L7 19l-4 1 1-4 12.5-12.5z"/>
                </svg>
              </button>
              <button
                type="button"
                class="btn-icon remove"
                (click)="removeTextEntry(entry.id)"
                [attr.aria-label]="'textEntry.remove' | translate"
              >
                <img src="/icons/trash_red.svg" alt="Remove" width="16" height="16" />
              </button>
            </div>
            }
            @for (file of uploadedFiles(); track file.id) {
            <div class="file-item" [class]="'status-' + file.status">
              <div class="file-icon">
                <img
                  [src]="getFileIcon(file.type)"
                  alt="File"
                  width="24"
                  height="24"
                />
              </div>

              <div class="file-info">
                <span class="file-name">{{ file.name }}</span>
                <span class="file-size">{{ formatFileSize(file.size) }}</span>
              </div>

              @if (file.status === 'uploading') {
              <div class="file-progress">
                <div class="progress-bar">
                  <div
                    class="progress-fill"
                    [style.width.%]="file.uploadProgress"
                  ></div>
                </div>
                <span class="progress-text">{{ file.uploadProgress }}%</span>
              </div>
              } @if (file.status === 'completed') {
              <div class="file-status success">
                <img
                  src="/icons/check-circle.svg"
                  alt="Success"
                  width="20"
                  height="20"
                />
              </div>
              } @if (file.status === 'error') {
              <div class="file-status error">
                @if (file.error) {
                <span class="error-text">{{ file.error }}</span>
                }
              </div>
              }

              <button
                class="btn-icon remove"
                (click)="removeFile(file.id)"
                type="button"
                [attr.aria-label]="'Remove ' + file.name"
              >
                <img
                  src="/icons/trash_red.svg"
                  alt="Remove"
                  width="16"
                  height="16"
                />
              </button>
            </div>
            }
          </div>
        </div>
        }
      </div>
    </div>
  `,
  changeDetection: ChangeDetectionStrategy.OnPush,
  styleUrl: './file-upload-step.component.scss',
  imports: [FormsModule, TranslatePipe, TextEntryDialogComponent],
})
export class FileUploadStepComponent implements OnInit {
  data = input.required<WizardData>();
  dataChange = output<Partial<WizardData>>();

  uploadedFiles = signal<UploadedFileInfo[]>([]);
  textEntries = signal<WizardTextEntry[]>([]);
  isDragging = signal(false);

  textDialogOpen = signal(false);
  textDialogMode = signal<'create' | 'edit'>('create');
  textDialogInitialTitle = signal('');
  textDialogInitialContent = signal('');
  textDialogResetToken = signal(0);
  editingEntryId = signal<string | null>(null);

  isMoodleAdditionalFiles = computed(() => {
    const data = this.data();
    return data.sourceType === 'moodle' && data.selectedCourses.length > 0;
  });

  totalSize = computed(() => {
    return this.uploadedFiles().reduce((sum, file) => sum + file.size, 0);
  });

  completedFiles = computed(() => {
    return this.uploadedFiles().filter((f) => f.status === 'completed').length;
  });

  ngOnInit(): void {
    const existingFiles = this.data().uploadedFiles;
    if (existingFiles && existingFiles.length > 0) {
      this.uploadedFiles.set(existingFiles);
    }
    const existingTextEntries = this.data().textEntries;
    if (existingTextEntries && existingTextEntries.length > 0) {
      this.textEntries.set(existingTextEntries);
    }
  }

  openCreateTextDialog(): void {
    this.editingEntryId.set(null);
    this.textDialogMode.set('create');
    this.textDialogInitialTitle.set('');
    this.textDialogInitialContent.set('');
    this.textDialogResetToken.update((v) => v + 1);
    this.textDialogOpen.set(true);
  }

  openEditTextDialog(entry: WizardTextEntry): void {
    this.editingEntryId.set(entry.id);
    this.textDialogMode.set('edit');
    this.textDialogInitialTitle.set(entry.title);
    this.textDialogInitialContent.set(entry.content);
    this.textDialogResetToken.update((v) => v + 1);
    this.textDialogOpen.set(true);
  }

  closeTextDialog(): void {
    this.textDialogOpen.set(false);
    this.editingEntryId.set(null);
  }

  onTextDialogSave(event: TextEntrySaveEvent): void {
    const id = this.editingEntryId();
    if (id) {
      this.textEntries.update((entries) =>
        entries.map((e) =>
          e.id === id ? { ...e, title: event.title, content: event.content } : e
        )
      );
    } else {
      const newEntry: WizardTextEntry = {
        id: `text-${Date.now()}-${Math.random()}`,
        title: event.title,
        content: event.content,
      };
      this.textEntries.update((entries) => [...entries, newEntry]);
    }
    this.textDialogOpen.set(false);
    this.editingEntryId.set(null);
    this.emitData();
  }

  removeTextEntry(id: string): void {
    this.textEntries.update((entries) => entries.filter((e) => e.id !== id));
    this.emitData();
  }

  onDragOver(event: DragEvent): void {
    event.preventDefault();
    event.stopPropagation();
    this.isDragging.set(true);
  }

  onDragLeave(event: DragEvent): void {
    event.preventDefault();
    event.stopPropagation();
    this.isDragging.set(false);
  }

  onDrop(event: DragEvent): void {
    event.preventDefault();
    event.stopPropagation();
    this.isDragging.set(false);

    const files = event.dataTransfer?.files;
    if (files) {
      this.processFiles(Array.from(files));
    }
  }

  onFileSelect(event: Event): void {
    const input = event.target as HTMLInputElement;
    if (input.files) {
      this.processFiles(Array.from(input.files));
      input.value = '';
    }
  }

  private processFiles(files: File[]): void {
    const validFiles = files.filter((file) => {
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
      // H5P files are zip archives, so browsers report empty/generic MIME types.
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
        console.warn(`File too large: ${file.name} (${file.size} bytes)`);
        return false;
      }

      return true;
    });

    if (validFiles.length === 0) {
      return;
    }

    const newFiles: UploadedFileInfo[] = validFiles.map((file) => ({
      id: `${Date.now()}-${Math.random()}`,
      file,
      name: file.name,
      size: file.size,
      type: file.type,
      uploadProgress: 0,
      status: 'pending',
    }));

    this.uploadedFiles.update((files) => [...files, ...newFiles]);

    newFiles.forEach((uploadedFile) => {
      this.simulateUpload(uploadedFile);
    });
  }

  private simulateUpload(uploadedFile: UploadedFileInfo): void {
    this.updateFileStatus(uploadedFile.id, 'uploading', 0);

    const interval = setInterval(() => {
      this.uploadedFiles.update((files) =>
        files.map((f) => {
          if (f.id === uploadedFile.id && f.status === 'uploading') {
            const newProgress = Math.min(f.uploadProgress + 10, 100);
            return { ...f, uploadProgress: newProgress };
          }
          return f;
        })
      );

      const currentFile = this.uploadedFiles().find(
        (f) => f.id === uploadedFile.id
      );
      if (currentFile && currentFile.uploadProgress >= 100) {
        clearInterval(interval);
        this.updateFileStatus(uploadedFile.id, 'completed');
        this.emitData();
      }
    }, 100);
  }

  private updateFileStatus(
    id: string,
    status: UploadedFileInfo['status'],
    progress?: number
  ): void {
    this.uploadedFiles.update((files) =>
      files.map((f) =>
        f.id === id
          ? {
              ...f,
              status,
              uploadProgress:
                progress !== undefined ? progress : f.uploadProgress,
            }
          : f
      )
    );
  }

  removeFile(id: string): void {
    this.uploadedFiles.update((files) => files.filter((f) => f.id !== id));
    this.emitData();
  }

  clearAll(): void {
    this.uploadedFiles.set([]);
    this.textEntries.set([]);
    this.emitData();
  }

  onForceOcrChange(checked: boolean): void {
    this.dataChange.emit({ forceOcr: checked });
  }

  private emitData(): void {
    this.dataChange.emit({
      uploadedFiles: this.uploadedFiles(),
      textEntries: this.textEntries(),
    });
  }

  getFileIcon(type: string): string {
    if (type.includes('pdf')) return '/icons/file.svg';
    if (type.includes('word')) return '/icons/file.svg';
    if (type.includes('powerpoint') || type.includes('presentation'))
      return '/icons/monitor.svg';
    return '/icons/file.svg';
  }

  formatFileSize(bytes: number): string {
    if (bytes === 0) return '0 Bytes';
    const k = 1024;
    const sizes = ['Bytes', 'KB', 'MB', 'GB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return Math.round((bytes / Math.pow(k, i)) * 100) / 100 + ' ' + sizes[i];
  }
}