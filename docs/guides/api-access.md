# How to query an Alice chatbot from your own RAG application

Alice exposes an OpenAI-compatible chat completions endpoint that lets you talk to one of your chatbots programmatically. You send a list of messages, you get back the assistant's answer grounded in that chatbot's knowledge base, plus citations to the source documents.

This guide walks through enabling API access on a chatbot, fetching its API key, and sending requests.

## What API access gives you

- A single endpoint, `POST /api/v1/chat/completions`, that follows the OpenAI Chat Completions schema (messages, streaming, etc.).
- Every request is routed through the chatbot's persona and retrieves from the chatbot's knowledge base, exactly like the web UI.
- Responses include `citations` referencing the source documents that grounded the answer.

The API key is tied to a single chatbot. If you want multiple chatbots, you enable API access on each one and use its own key.

## 1. Enable API access on a chatbot

1. Go to [alice.skilltech.tools](https://alice.skilltech.tools/) and open the chatbot you want to query.
2. Open the **Settings** tab.
3. Scroll to **API Access** and toggle it on.
4. Two new fields appear:
    - **API endpoint**: the full URL you will POST to, for example `https://alice.skilltech.tools/api/v1/chat/completions`.
    - **API key**: a long token unique to this chatbot. Click the eye icon to reveal it and the copy icon to copy it.

Treat the API key like a password. Anyone who has it can send messages to your chatbot, which counts against your usage. If you think it has leaked, disable API access and re-enable it to rotate the underlying chatbot token, then ask an administrator if you need a more controlled rotation.

## 2. Send a request

Authenticate with a standard `Authorization: Bearer <api_key>` header. The request body follows the OpenAI Chat Completions shape:

```json
{
  "messages": [
    {"role": "user", "content": "What is the deadline for the final assignment?"}
  ],
  "stream": false
}
```

Fields:

- `messages` (required): an array of `{role, content}` objects. `role` is one of `user`, `assistant`, or `system`. To carry a multi-turn conversation, send the full history each request.
- `stream` (optional, default `true`): if `true`, the response is a Server-Sent Events stream; if `false`, you get a single JSON response.
- `model` (optional, default `"default"`): accepted for OpenAI compatibility but ignored. The chatbot's configured model is always used.

### Example: non-streaming with curl

```bash
curl https://alice.skilltech.tools/api/v1/chat/completions \
  -H "Authorization: Bearer YOUR_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "messages": [
      {"role": "user", "content": "Summarise the key points of week 3."}
    ],
    "stream": false
  }'
```

You get back JSON shaped like an OpenAI completion, with an extra `citations` field:

```json
{
  "id": "chatcmpl-…",
  "object": "chat.completion",
  "created": 1736500000,
  "model": "My Chatbot",
  "choices": [
    {
      "index": 0,
      "message": {
        "role": "assistant",
        "content": "Week 3 covers… [1] … [2]."
      },
      "finish_reason": "stop"
    }
  ],
  "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
  "citations": [
    {
      "id": 1,
      "file_name": "week3-slides.pdf",
      "file_id": "…",
      "source_url": "https://…",
      "score": 0.87
    },
    {
      "id": 2,
      "file_name": "week3-reading.pdf",
      "file_id": "…",
      "source_url": "https://…",
      "score": 0.81
    }
  ]
}
```

The `[1]`, `[2]` markers in the assistant message correspond to the `id` field of each citation. Only citations actually referenced in the answer are returned. The `usage` token counts are placeholders and not currently populated.

### Example: using the OpenAI Python SDK

Because the endpoint is OpenAI-compatible, you can point the official SDK at it and reuse your existing client code:

```python
from openai import OpenAI

client = OpenAI(
    api_key="YOUR_API_KEY",
    base_url="https://alice.skilltech.tools/api/v1",
)

response = client.chat.completions.create(
    model="default",
    messages=[
        {"role": "user", "content": "Summarise the key points of week 3."},
    ],
    stream=False,
)

print(response.choices[0].message.content)
```

Citations are not part of the OpenAI schema, so the SDK will not surface them. To read them, fall back to a plain HTTP client (`httpx`, `requests`, `fetch`) and parse the `citations` field yourself.

### Example: streaming

Set `"stream": true` (the default) to receive a Server-Sent Events response. The body is a sequence of `data: …` lines with the same delta shape OpenAI uses:

```
data: {"choices":[{"delta":{"content":"Week"}}]}

data: {"choices":[{"delta":{"content":" 3"}}]}

…

data: [DONE]

data: {"citations":[{"id":1,"file_name":"week3-slides.pdf", …}]}
```

Two things to note compared to OpenAI:

- After `data: [DONE]`, Alice sends one additional event containing the `citations` array. Keep reading the stream past `[DONE]` if you want citations.
- If no citations apply to the answer, the extra event is omitted.

## 3. Using Alice as the backend of your own RAG app

A typical integration looks like this:

1. Your app collects the user's question (and any prior turns of the conversation).
2. Your app POSTs to `/api/v1/chat/completions` with the full message history and your chatbot's API key.
3. Your app streams the response back to its UI, then renders the citations once they arrive.

You do not need to run your own retriever, vector store, or prompt template: the chatbot's persona, knowledge base, and retrieval settings configured in Alice are applied automatically on every request. If you want to change retrieval behaviour or grounding policy, edit the chatbot in the Alice UI rather than your client code.

If you need multiple personas or knowledge bases, create multiple chatbots and switch API keys in your application based on which one should answer.

## Limits and errors

- **Rate limit**: 30 requests per minute per client IP. Exceeding this returns HTTP `429`.
- **Authentication errors**:
    - `401 Missing Authorization header`: no `Authorization` header was sent.
    - `401 Invalid Authorization header format`: header was not `Bearer <token>`.
    - `401 Invalid API key`: the token does not match any chatbot.
- **Authorisation errors**:
    - `403 API access is not enabled for this chatbot`: toggle **API Access** on in the chatbot's settings.
    - `403 Chatbot is disabled`: the chatbot itself is disabled. Re-enable it from the chatbot list.

