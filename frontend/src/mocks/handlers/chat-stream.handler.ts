import { http, HttpResponse } from 'msw';
import { environment } from '../../environments/environment';
import { mockStore } from '../store/mock-store';
import { pickReplyFromFixture } from '../fixtures/chat-responses.fixture';

const api = environment.apiBaseUrl;

interface ChatMessage {
  role: string;
  content: string;
}

interface ChatStreamRequest {
  messages: ChatMessage[];
  password?: string;
}

function sseFrame(payload: unknown): string {
  return `data: ${JSON.stringify(payload)}\n\n`;
}

export const chatStreamHandler = http.post(
  `${api}/chatbots/:id/chat/stream`,
  async ({ params, request }) => {
    const body = (await request.json()) as ChatStreamRequest;
    const chatbot = mockStore.getChatbot(params['id'] as string);
    const citeSources = chatbot?.cite_sources ?? false;
    const lastMessage = body.messages[body.messages.length - 1]?.content ?? '';
    const reply = pickReplyFromFixture(lastMessage, citeSources);

    const encoder = new TextEncoder();
    const stream = new ReadableStream({
      start(controller) {
        let i = 0;
        const signal = request.signal;
        const abort = () => {
          try {
            controller.close();
          } catch {
            /* already closed */
          }
        };
        signal.addEventListener('abort', abort);

        const tick = () => {
          if (signal.aborted) return;
          if (i < reply.tokens.length) {
            controller.enqueue(
              encoder.encode(
                sseFrame({
                  choices: [{ delta: { content: reply.tokens[i] } }],
                })
              )
            );
            i++;
            setTimeout(tick, 30);
            return;
          }
          if (reply.citations && reply.citations.length > 0) {
            controller.enqueue(
              encoder.encode(sseFrame({ citations: reply.citations }))
            );
          }
          controller.enqueue(
            encoder.encode(
              sseFrame({ choices: [{ delta: {}, finish_reason: 'stop' }] })
            )
          );
          signal.removeEventListener('abort', abort);
          controller.close();
        };
        tick();
      },
    });

    return new HttpResponse(stream, {
      headers: {
        'Content-Type': 'text/event-stream',
        'Cache-Control': 'no-cache',
      },
    });
  }
);
