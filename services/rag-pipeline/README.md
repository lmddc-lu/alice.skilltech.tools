
## Supported file formats
DOCX = "docx"
PPTX = "pptx"
HTML = "html"
IMAGE = "image"
PDF = "pdf"
ASCIIDOC = "asciidoc"
MD = "md"
CSV = "csv"
XLSX = "xlsx"
XML_USPTO = "xml_uspto"
XML_JATS = "xml_jats"
METS_GBS = "mets_gbs"
JSON_DOCLING = "json_docling"
AUDIO = "audio"

## Test commands
curl -X POST http://localhost:1416/chat/completions   -H "Content-Type: application/json"   -d '{    "model": "rag_query",    "messages": [      {        "role": "user",         "content": "Can you sum up the proposition?"      }    ],    "index_name": "hello",    "temperature": 0.7,    "max_tokens": 500,    "top_k": 5, "custom_id": "testid99" }'

curl -X POST http://localhost:1416/rag_query/run -H "accept: application/json" -H "Content-Type: application/json" -d '{"question": "Tell me about this meeting, what was it about? ", "top_k": 3, "conversation_history": [], "index_name": "hello"}'


curl -X 'POST' \
  'http://localhost:1416/session_manager/run' \
  -H 'accept: application/json' \
  -H 'Content-Type: application/json' \
  -d '{
  "action": "get_sources",
  "session_id": "testid99"
}'