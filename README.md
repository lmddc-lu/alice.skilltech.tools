# Alice

Alice is a tool to create educational chatbots grounded in knowledge bases
assembled from course materials: uploaded documents (PDF, DOCX, PPTX, H5P,
SCORM, images, plain text) and content synced from Moodle. 

## How it works

**Educators** log in via OIDC, create a chatbot, pick a persona, and attach
a knowledge base by uploading files or syncing a Moodle course. They then
share the chatbot via a URL (public, password-protected, or SSO-only).

**Learners** open the URL and chat. Each answer is grounded in the
knowledge base and returned with citations to the source documents.

## Architecture

Four services:

- **`frontend/`**: Angular UI: dashboard for managing chatbots and
  knowledge bases, plus the learner-facing chat interface.
- **`api/`**: FastAPI backend. Owns chatbots, knowledge bases, users,
  jobs, and Moodle integrations. Persists to PostgreSQL, stores uploads in S3 (Garage), publishes ingestion jobs to RabbitMQ.
- **`services/rag-pipeline/`**: Haystack-based AI service. Parses documents via
  a Docling Serve instance, embeds and indexes chunks, and answers queries
  against an OpenAI-compatible LLM endpoint.
- **`sync/`**: Background worker. Consumes RabbitMQ jobs, pulls files
  from S3 or Moodle, and drives the RAG pipeline ingestion.

## Stack

- Docker Compose for development and production
- Angular frontend
- FastAPI for the Python API
    - Alembic for database migrations
    - SQLModel for the Python ORM
    - UV for Python package management
- PostgreSQL as the SQL database
- Garage for S3 storage (currently included in Docker Compose)
- Qdrant as the vector store
- Valkey for ingestion job tracking and RAG session storage
- RabbitMQ for message queueing
    - FastStream for the Python client integrated with FastAPI
    - Pika for the Python client
- Haystack for RAG pipeline management
    - Docling Serve for file parsing
- An OpenAI compatible endpoint for LLM/Embeddings inference

## Documentation

Documentation is available [Here](https://documentation.skilltech.tools/platform/alice.skilltech.tools/) or locally in the docs/ folder. 

## License

This project is licensed under the GNU AFFERO GENERAL PUBLIC LICENSE Version 3, 19 November 2007, you may obtain the source code on [Github](). Please check the CREDITS.md file at the root of the repository for more details about the licences and contributors.

---

Created by [LMDDC](https://lmddc.lu).


