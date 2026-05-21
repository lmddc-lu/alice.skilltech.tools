# How to install and run Alice

This guide walks through installing Alice on a single host with Docker Compose. You will start the main stack (frontend, API, sync worker, database, object storage, queue), provision object storage, then start the RAG pipeline that handles document parsing and inference.

Alice is built around the principle of only using open-source components and running everything ourselves. For that reason, we did not develop a managed cloud deployment, the project is intended to be self-hosted.

## Overview

Alice is made of two Docker Compose stacks:

- **Main stack** — `docker-compose.yml` at the repo root. Runs the frontend, API, sync worker, PostgreSQL, Redis, RabbitMQ, and a bundled Garage instance for S3-compatible storage.
- **RAG pipeline** — `services/docker-compose-full.yml`, or `docker-compose-full-gpu.yml` if you have a GPU. Runs Haystack, Docling Serve, Qdrant, and the PII filter.

It is recommended to run the RAG pipeline on a machine with a GPU to accelerate document parsing. In this setup, we will setup both stacks on the same machine, but they can be separated as long as they are on the same network.

## Requirements

- Docker and Docker Compose.
- An OIDC provider for educator login.
- An S3-compatible object store. The main stack uses [Garage](https://garagehq.deuxfleurs.fr/) by default; you can also point Alice at your own S3.
- An OpenAI-compatible endpoint for LLM and embedding inference.

## 1. Configure the main stack

1. Clone the repository.
2. Copy the environment template: `cp .env.example .env`.
3. Edit `.env`. At minimum, fill in the **OAuth / OIDC** section with the credentials from your OIDC provider.
4. If you are using the bundled Garage, follow the [Garage quick-start](https://garagehq.deuxfleurs.fr/documentation/quick-start/) to create a `.garage_conf/garage.toml` file. If you are bringing your own S3, remove the Garage service from `docker-compose.yml`.

## 2. Start the main stack

```bash
docker compose --profile dev up --build -d
```

At this point the API will run, but it cannot store uploads yet because Garage has no bucket and no access keys. Provision them in the next step.

## 3. Provision Garage object storage

Open the Garage web UI at [localhost:3909](http://localhost:3909) and:

1. Go to **Cluster**, click your node, then click **Assign**.
2. Set **Zone** to `garage` and **Capacity** to whatever you want to allocate to S3. Confirm and click **Apply**.
3. In the **Bucket** tab, create a bucket whose name matches the `MINIO_BUCKET_NAME` value in your `.env`.
4. In the **Keys** tab, create a new key (the name does not matter).
5. Back in **Buckets**, open your bucket, click **Manage > Permissions > Allow Key**, and grant read, write, and owner to your key.
6. Return to **Keys**, copy the **Key ID** and **Secret key**, and paste them into `MINIO_ACCESS_KEY` and `MINIO_SECRET_KEY` in your `.env`.

## 4. Restart the main stack

Apply the new S3 credentials:

```bash
docker compose --profile dev down
docker compose --profile dev up --build -d
```

The API health check will still fail with:

```
WARNING:app.api_v2.routes.utils:Hayhooks health check failed: All connection attempts failed
```

This is expected, the RAG pipeline is not running yet.

## 5. Start the RAG pipeline

```bash
cd services
cp .env.example .env
```

Edit `services/.env` and set `LLM_API_BASE`, `LLM_API_KEY`, `EMBED_API_BASE`, and `EMBED_API_KEY` to a valid OpenAI-compatible endpoint.

Then start the pipeline. Without a GPU:

```bash
docker compose -f docker-compose-full.yml up --build -d
```

With a GPU:

```bash
docker compose -f docker-compose-full-gpu.yml up --build -d
```

Once it is up, the main stack's Hayhooks health check should pass.

## 6. Verify the installation

Open [localhost:4200](http://localhost:4200). Log in via OIDC, create a chatbot, upload a small document, and start a conversation with it. If the chatbot answers with a citation back to your document, everything is wired up correctly.
