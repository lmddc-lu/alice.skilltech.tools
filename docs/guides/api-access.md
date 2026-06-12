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
      {"role": "user", "content": "What is Alice?"}
    ],
    "stream": false
  }'
```

You get back JSON shaped like an OpenAI completion, with an extra `citations` field:

```json
{
  "id": "chatcmpl-8f561e62-f1ad-400b-aeaa-a6e21f3b8582",
  "object": "chat.completion",
  "created": 1781080115,
  "model": "Alice kb",
  "choices": [
    {
      "index": 0,
      "message": {
        "role": "assistant",
        "content": "Alice is a platform that lets educators create AI‑powered chatbots that answer questions using only the course materials you upload (slides, readings, handouts, etc.) or sync from Moodle. It builds a knowledge base from those documents, so every response is sourced from that base and includes citations back to the original files [1]. The tool is aimed at teachers and institutions that want a reliable, course‑specific AI assistant while keeping their data on‑premises and under their control; it is open‑source, supports access‑control options, and lets you define the bot’s persona [3]."
      },
      "finish_reason": "stop"
    }
  ],
  "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
  "citations": [
    {
      "id": 1,
      "file_name": "article alice.pdf",
      "file_id": "af4ca477-1afe-4415-b912-390b0a21afef",
      "source_url": null,
      "score": 0.5948779
    },
    {
      "id": 3,
      "file_name": "article alice.pdf",
      "file_id": "af4ca477-1afe-4415-b912-390b0a21afef",
      "source_url": null,
      "score": 0.58045
    }
  ]
}
```

The `[1]`, `[3]` markers in the assistant message correspond to the `id` field of each citation. Only citations actually referenced in the answer are returned, so the ids are not necessarily contiguous (here `[2]` was retrieved but not cited, so it is omitted). `source_url` is `null` for documents you uploaded directly; it is populated for synced sources that have a canonical URL. The `usage` token counts are placeholders and not currently populated.

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
        {"role": "user", "content": "What is Alice?"},
    ],
    stream=False,
)

print(response.choices[0].message.content)
```

This prints the assistant's answer, for example:

```
Alice is a self‑hosted, open‑source platform that lets educators create AI chatbots that are grounded exclusively in the course materials you upload (slides, readings, handouts, etc.) or sync from Moodle. Every answer the bot gives is drawn from that knowledge base and includes citations back to the original documents, so students see exactly where the information comes from. The service is designed for educators and institutions that want a reliable, course‑specific AI assistant while keeping their data under their own control [1][3]
```

Citations are not part of the OpenAI schema, so the SDK will not surface them. To read them, fall back to a plain HTTP client (`httpx`, `requests`, `fetch`) and parse the `citations` field yourself.

### Example: streaming

Set `"stream": true` (the default) to receive a Server-Sent Events response. The body is a sequence of `data: …` lines with the same delta shape OpenAI uses (some OpenAI-compatible fields such as `reasoning_content`, `tool_calls` and `refusal` are always present but usually `null`):

```
data: {"id":"chatcmpl-…","object":"chat.completion.chunk","created":1781080141,"model":"Alice kb","choices":[{"index":0,"delta":{"role":"assistant","content":"Alice","reasoning_content":null,"tool_calls":null,"refusal":null},"finish_reason":null,"logprobs":null,"message":null}],"usage":null,"system_fingerprint":null}

data: {"id":"chatcmpl-…","object":"chat.completion.chunk","created":1781080141,"model":"Alice kb","choices":[{"index":0,"delta":{"content":" is"},"finish_reason":null}],"usage":null}

…

data: {"id":"chatcmpl-…","object":"chat.completion.chunk","created":1781080141,"model":"Alice kb","choices":[{"index":0,"delta":{"content":""},"finish_reason":"stop"}],"usage":null}

data: [DONE]

data: {"citations": [{"id": 1, "file_name": "article alice.pdf", "file_id": "af4ca477-1afe-4415-b912-390b0a21afef", "source_url": null, "score": 0.5948779}, {"id": 3, "file_name": "article alice.pdf", "file_id": "af4ca477-1afe-4415-b912-390b0a21afef", "source_url": null, "score": 0.58045}]}
```

Differences with OpenAI spec:

- After `data: [DONE]`, Alice sends one additional event containing the `citations` array. The `[DONE]` sentinel is sent first so a standard OpenAI client stops cleanly there; keep reading one event past `[DONE]` if you want citations.
- If no citations apply to the answer, the extra event is omitted (so `[DONE]` is the final line).
- The stream begins with several chunks whose `delta.content` is an empty string; this is normal concatenate the `content` deltas and the empty ones simply contribute nothing.


## Limits and errors

- **Rate limit**: Exceeding the rate limit returns HTTP `429`.
- **Authentication errors**:
    - `401 Missing Authorization header`: no `Authorization` header was sent.
    - `401 Invalid Authorization header format`: header was not `Bearer <token>`.
    - `401 Invalid API key`: the token does not match any chatbot.
- **Authorisation errors**:
    - `403 API access is not enabled for this chatbot`: toggle **API Access** on in the chatbot's settings.
    - `403 Chatbot is disabled`: the chatbot itself is disabled. Re-enable it from the chatbot list.

