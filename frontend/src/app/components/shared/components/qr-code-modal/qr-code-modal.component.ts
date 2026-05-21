import {
  Component,
  ChangeDetectionStrategy,
  input,
  output,
} from '@angular/core';
import { TranslatePipe } from '@ngx-translate/core';
import { QRCodeComponent } from 'angularx-qrcode';

@Component({
  selector: 'app-qr-code-modal',
  imports: [TranslatePipe, QRCodeComponent],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <div class="modal-overlay" (click)="close.emit()">
      <div class="modal-container qr-modal" (click)="$event.stopPropagation()">
        <div class="modal-header">
          <h2>{{ "editChatbot.qrCodeTitle" | translate }}</h2>
          <button
            type="button"
            class="close-button"
            aria-label="Close modal"
            (click)="close.emit()"
          >
            <svg
              width="24"
              height="24"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              stroke-width="2"
            >
              <path d="M18 6L6 18M6 6l12 12" />
            </svg>
          </button>
        </div>

        <div class="modal-content qr-content">
          <div class="qr-code-container">
            <qrcode
              [qrdata]="chatbotUrl()"
              [width]="256"
              [errorCorrectionLevel]="'M'"
              [imageSrc]="'favicon.ico'"
            ></qrcode>
          </div>

          <div class="qr-info">
            <p class="qr-description">
              {{ "editChatbot.qrCodeDescription" | translate }}
            </p>
            <div class="qr-url">
              <code>{{ chatbotUrl() }}</code>
            </div>
          </div>
        </div>

        <div class="modal-footer">
          <button
            class="btn btn-secondary"
            (click)="downloadQRCode()"
            type="button"
          >
            <img
              src="/icons/download.svg"
              alt="Download"
              width="16"
              height="16"
            />
            {{ "editChatbot.downloadQR" | translate }}
          </button>
          <button
            class="btn btn-primary"
            (click)="close.emit()"
            type="button"
          >
            {{ "editChatbot.close" | translate }}
          </button>
        </div>
      </div>
    </div>
  `,
})
export class QrCodeModalComponent {
  chatbotUrl = input.required<string>();
  chatbotName = input.required<string>();

  close = output<void>();

  downloadQRCode(): void {
    const qrElement = document.querySelector(
      '.qr-code-container canvas'
    ) as HTMLCanvasElement;
    if (qrElement) {
      const url = qrElement.toDataURL('image/png');
      const link = document.createElement('a');
      link.href = url;
      link.download = `${this.chatbotName() || 'chatbot'}-qr-code.png`;
      link.click();
    }
  }
}
