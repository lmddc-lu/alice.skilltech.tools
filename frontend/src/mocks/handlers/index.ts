import { authHandlers } from './auth.handlers';
import { chatbotHandlers } from './chatbot.handlers';
import { moodleHandlers } from './moodle.handlers';
import { chatStreamHandler } from './chat-stream.handler';

export const handlers = [
  ...authHandlers,
  chatStreamHandler,
  ...chatbotHandlers,
  ...moodleHandlers,
];
