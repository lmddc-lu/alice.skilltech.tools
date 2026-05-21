import { ChatbotStatus } from '../../app/interfaces/chatbot-i';
import {
  mockChatbotReadyBasic,
  mockChatbotProcessing,
  mockChatbotError,
} from './chatbots.fixture';
import {
  readyFiles,
  processingFiles,
  errorFiles,
  freeTextOnlyFiles,
  jobFilesFor,
} from './files.fixture';
import type { MockChatbotState } from '../store/mock-store';

function readyBasic(): MockChatbotState[] {
  const files = readyFiles();
  return [
    {
      chatbot: { ...mockChatbotReadyBasic, status: ChatbotStatus.READY },
      files,
      jobFiles: jobFilesFor(files),
      jobProgress: { current: files.length, total: files.length },
    },
  ];
}

function processingMidway(): MockChatbotState[] {
  const files = processingFiles();
  const done = files.filter((f) => f.ingestion_state === 'ingested').length;
  return [
    {
      chatbot: { ...mockChatbotProcessing, status: ChatbotStatus.PROCESSING },
      files,
      jobFiles: jobFilesFor(files),
      jobProgress: { current: done, total: files.length },
    },
  ];
}

function errorWithFailedFiles(): MockChatbotState[] {
  const files = errorFiles();
  return [
    {
      chatbot: { ...mockChatbotError, status: ChatbotStatus.ERROR },
      files,
      jobFiles: jobFilesFor(files),
      jobProgress: { current: files.length, total: files.length },
    },
  ];
}

function empty(): MockChatbotState[] {
  return [];
}

function moodleSource(): MockChatbotState[] {
  const files = readyFiles().slice(0, 2);
  return [
    {
      chatbot: {
        ...mockChatbotReadyBasic,
        id: 'cb-moodle-1',
        name: 'Histoire contemporaine (Moodle)',
        description: 'Contenu synchronisé depuis Moodle.',
        datasource_types: ['MOODLE'],
        status: ChatbotStatus.READY,
      },
      files,
      jobFiles: jobFilesFor(files),
      jobProgress: { current: files.length, total: files.length },
    },
  ];
}

function freeTextOnly(): MockChatbotState[] {
  const files = freeTextOnlyFiles();
  return [
    {
      chatbot: {
        ...mockChatbotReadyBasic,
        id: 'cb-freetext-1',
        name: 'Assistant notes personnelles',
        description: 'Chatbot alimenté uniquement par des entrées texte.',
        status: ChatbotStatus.READY,
      },
      files,
      jobFiles: jobFilesFor(files),
      jobProgress: { current: files.length, total: files.length },
    },
  ];
}

function readyWithCitations(): MockChatbotState[] {
  const files = readyFiles();
  return [
    {
      chatbot: {
        ...mockChatbotReadyBasic,
        id: 'cb-cite-1',
        name: 'Histoire (avec citations)',
        cite_sources: true,
        status: ChatbotStatus.READY,
      },
      files,
      jobFiles: jobFilesFor(files),
      jobProgress: { current: files.length, total: files.length },
    },
  ];
}

export const SCENARIOS: Record<string, () => MockChatbotState[]> = {
  'ready-basic': readyBasic,
  'processing-midway': processingMidway,
  'error-with-failed-files': errorWithFailedFiles,
  empty,
  'moodle-source': moodleSource,
  'free-text-only': freeTextOnly,
  'ready-with-citations': readyWithCitations,
};

export type ScenarioName = keyof typeof SCENARIOS;
