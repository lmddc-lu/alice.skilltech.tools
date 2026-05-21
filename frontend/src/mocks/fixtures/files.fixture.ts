import {
  ChatbotFile,
  JobFile,
  JobFileState,
} from '../../app/interfaces/chatbot-i';

const baseDate = '2026-04-01T10:00:00.000Z';

function cloneFiles(files: ChatbotFile[]): ChatbotFile[] {
  return files.map((f) => ({ ...f }));
}

function cloneJobFiles(files: JobFile[]): JobFile[] {
  return files.map((f) => ({ ...f }));
}

function jobFileFromChatbotFile(file: ChatbotFile): JobFile {
  return {
    id: `job-${file.id}`,
    external_file_id: file.id,
    filename: file.filename,
    state: (file.ingestion_state ?? 'pending') as JobFileState,
    error_message: file.ingestion_error,
    error_code: file.ingestion_error_code,
    created_at: baseDate,
    updated_at: baseDate,
  };
}

const readyFilesTemplate: ChatbotFile[] = [
  {
    id: 'file-ready-pdf',
    filename: 'chapitre-1-revolution-francaise.pdf',
    size: 3_145_728,
    mime_type: 'application/pdf',
    upload_date: baseDate,
    status: 'uploaded',
    ingestion_state: 'ingested',
    ingestion_error: null,
    ingestion_error_code: null,
  },
  {
    id: 'file-ready-docx',
    filename: 'notes-de-cours.docx',
    size: 524_288,
    mime_type:
      'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
    upload_date: baseDate,
    status: 'uploaded',
    ingestion_state: 'ingested',
    ingestion_error: null,
    ingestion_error_code: null,
  },
  {
    id: 'file-ready-text',
    filename: 'Résumé oral',
    size: 1024,
    mime_type: 'text/plain',
    upload_date: baseDate,
    status: 'uploaded',
    is_free_text: true,
    ingestion_state: 'ingested',
    ingestion_error: null,
    ingestion_error_code: null,
  },
];

const processingFilesTemplate: ChatbotFile[] = [
  {
    id: 'file-proc-done-1',
    filename: 'manuel-chapitre-1.pdf',
    size: 8_388_608,
    mime_type: 'application/pdf',
    upload_date: baseDate,
    status: 'uploaded',
    ingestion_state: 'ingested',
    ingestion_error: null,
    ingestion_error_code: null,
  },
  {
    id: 'file-proc-done-2',
    filename: 'fiche-exercices.pdf',
    size: 2_097_152,
    mime_type: 'application/pdf',
    upload_date: baseDate,
    status: 'uploaded',
    ingestion_state: 'ingested',
    ingestion_error: null,
    ingestion_error_code: null,
  },
  {
    id: 'file-proc-done-3',
    filename: 'annexes.html',
    size: 20_480,
    mime_type: 'text/html',
    upload_date: baseDate,
    status: 'uploaded',
    ingestion_state: 'ingested',
    ingestion_error: null,
    ingestion_error_code: null,
  },
  {
    id: 'file-proc-running',
    filename: 'video-cours.mp4',
    size: 104_857_600,
    mime_type: 'video/mp4',
    upload_date: baseDate,
    status: 'processing',
    ingestion_state: 'ingesting',
    ingestion_error: null,
    ingestion_error_code: null,
  },
  {
    id: 'file-proc-pending',
    filename: 'devoir-maison.pdf',
    size: 614_400,
    mime_type: 'application/pdf',
    upload_date: baseDate,
    status: 'uploaded',
    ingestion_state: 'pending',
    ingestion_error: null,
    ingestion_error_code: null,
  },
];

const errorFilesTemplate: ChatbotFile[] = [
  {
    id: 'file-err-empty',
    filename: 'document-vide.pdf',
    size: 2048,
    mime_type: 'application/pdf',
    upload_date: baseDate,
    status: 'error',
    ingestion_state: 'failed',
    ingestion_error: 'Could not process file',
    ingestion_error_code: 'empty_content',
  },
  {
    id: 'file-err-image',
    filename: 'scan-manuscrit.pdf',
    size: 1_572_864,
    mime_type: 'application/pdf',
    upload_date: baseDate,
    status: 'error',
    ingestion_state: 'failed',
    ingestion_error: 'Could not process file',
    ingestion_error_code: 'empty_content',
  },
];

const freeTextOnlyTemplate: ChatbotFile[] = [
  {
    id: 'file-text-intro',
    filename: 'Introduction au cours',
    size: 2048,
    mime_type: 'text/plain',
    upload_date: baseDate,
    status: 'uploaded',
    is_free_text: true,
    ingestion_state: 'ingested',
    ingestion_error: null,
    ingestion_error_code: null,
  },
  {
    id: 'file-text-methode',
    filename: 'Méthodologie',
    size: 4096,
    mime_type: 'text/plain',
    upload_date: baseDate,
    status: 'uploaded',
    is_free_text: true,
    ingestion_state: 'ingested',
    ingestion_error: null,
    ingestion_error_code: null,
  },
];

export function readyFiles(): ChatbotFile[] {
  return cloneFiles(readyFilesTemplate);
}

export function processingFiles(): ChatbotFile[] {
  return cloneFiles(processingFilesTemplate);
}

export function errorFiles(): ChatbotFile[] {
  return cloneFiles(errorFilesTemplate);
}

export function freeTextOnlyFiles(): ChatbotFile[] {
  return cloneFiles(freeTextOnlyTemplate);
}

export function jobFilesFor(files: ChatbotFile[]): JobFile[] {
  return cloneJobFiles(files.map(jobFileFromChatbotFile));
}

export const defaultTextEntries: Record<string, { title: string; content: string }> = {
  'file-ready-text': {
    title: 'Résumé oral',
    content:
      '# Résumé du cours\n\nLa Révolution française commence en 1789 avec la prise de la Bastille. Les causes principales sont la crise financière, les inégalités sociales, et les idées des Lumières.',
  },
  'file-text-intro': {
    title: 'Introduction au cours',
    content:
      '# Bienvenue\n\nCe chatbot vous accompagne tout au long du semestre. N\'hésitez pas à lui poser des questions sur les concepts abordés en cours.',
  },
  'file-text-methode': {
    title: 'Méthodologie',
    content:
      '# Méthodologie\n\n1. Lire attentivement la question\n2. Identifier les mots-clés\n3. Structurer la réponse en paragraphes\n4. Citer les sources',
  },
};
