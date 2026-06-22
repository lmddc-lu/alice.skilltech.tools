from pathlib import Path
from typing import Any

from config import EMBEDDING_DIM, USE_SPARSE_EMBEDDINGS
from loguru import logger


def list_files(
    document_store, index_name: str | None, default_index: str
) -> dict[str, Any]:
    """List all files currently in the vector store."""
    try:
        all_docs = document_store.filter_documents()

        file_counts = {}
        for doc in all_docs:
            # prefer flat metadata stamped by DoclingChunker; fall back to dl_meta
            filename = doc.meta.get("filename") or doc.meta.get("file_name", "unknown")
            mimetype = doc.meta.get("mime_type", "unknown")

            dl_meta = doc.meta.get("dl_meta", {})
            docling_meta = dl_meta.get("meta", {})
            origin = docling_meta.get("origin", {})
            if filename == "unknown":
                filename = origin.get("filename", "unknown")
            if mimetype == "unknown":
                mimetype = origin.get("mimetype", "unknown")
            binary_hash = origin.get("binary_hash", "unknown")

            has_sparse = (
                hasattr(doc, "sparse_embedding") and doc.sparse_embedding is not None
            )

            if filename not in file_counts:
                file_counts[filename] = {
                    "file_path": filename,
                    "file_name": Path(filename).name
                    if filename != "unknown"
                    else "unknown",
                    "document_count": 0,
                    "mimetype": mimetype,
                    "binary_hash": binary_hash,
                    "source_type": mimetype,
                    "has_sparse_embeddings": has_sparse,
                }
            file_counts[filename]["document_count"] += 1

        files_list = sorted(file_counts.values(), key=lambda x: x["file_name"])

        return {
            "success": True,
            "action": "list",
            "total_files": len(files_list),
            "total_documents": len(all_docs),
            "index_name": index_name or default_index,
            "hybrid_search_enabled": document_store.use_sparse_embeddings,
            "files": files_list,
        }

    except Exception as e:
        logger.error(f"Error listing files: {e}")
        return {
            "success": False,
            "action": "list",
            "error": str(e),
            "total_files": 0,
            "total_documents": 0,
            "index_name": index_name or default_index,
            "hybrid_search_enabled": USE_SPARSE_EMBEDDINGS,
            "files": [],
        }


def delete_documents(
    document_store,
    file_paths: list[str] | None = None,
    file_names: list[str] | None = None,
    index_name: str | None = None,
    default_index: str = "Document",
    file_ids: list[str] | None = None,
) -> dict[str, Any]:
    """Delete documents matching the given file_ids, paths, or names.

    file_ids match the stable meta.file_id stamped at ingestion and are the
    rename-proof path (a server-side filter, immune to any filename change a
    converter makes). file_paths/file_names fall back to origin-filename
    matching for chunks that carry no file_id (e.g. legacy bare ingests).
    """
    if not file_paths and not file_names and not file_ids:
        return {
            "success": False,
            "action": "delete",
            "error": "No file_ids, file_paths, or file_names provided",
            "total_documents_removed": 0,
            "index_name": index_name or default_index,
            "hybrid_search_enabled": USE_SPARSE_EMBEDDINGS,
        }

    try:
        removed_count = 0
        removed_files = []
        errors = []

        for file_id in file_ids or []:
            try:
                matching_docs = document_store.filter_documents(
                    filters={
                        "operator": "==",
                        "field": "meta.file_id",
                        "value": file_id,
                    }
                )
                if matching_docs:
                    document_store.delete_documents(
                        document_ids=[doc.id for doc in matching_docs]
                    )
                    removed_count += len(matching_docs)
                    removed_files.append(
                        {
                            "file_id": file_id,
                            "documents_removed": len(matching_docs),
                            "method": "file_id_match",
                        }
                    )
                    logger.info(
                        f"Removed {len(matching_docs)} documents for file_id: {file_id}"
                    )
                else:
                    removed_files.append(
                        {
                            "file_id": file_id,
                            "documents_removed": 0,
                            "method": "file_id_match",
                            "note": "No documents found",
                        }
                    )
            except Exception as e:
                error_msg = f"Error removing documents for file_id '{file_id}': {e}"
                errors.append(error_msg)
                logger.error(error_msg)

        all_names_to_remove = []
        if file_paths:
            all_names_to_remove.extend(file_paths)
        if file_names:
            all_names_to_remove.extend(file_names)

        all_names_to_remove = list(set(all_names_to_remove))

        for filename in all_names_to_remove:
            try:
                all_docs = document_store.filter_documents()
                matching_docs = []

                for doc in all_docs:
                    dl_meta = doc.meta.get("dl_meta", {})
                    docling_meta = dl_meta.get("meta", {})
                    origin = docling_meta.get("origin", {})
                    doc_filename = origin.get("filename", "")

                    if doc_filename == filename or Path(doc_filename).name == filename:
                        matching_docs.append(doc)

                if matching_docs:
                    doc_ids = [doc.id for doc in matching_docs]
                    document_store.delete_documents(document_ids=doc_ids)
                    removed_count += len(matching_docs)
                    removed_files.append(
                        {
                            "file_name": filename,
                            "documents_removed": len(matching_docs),
                            "method": "filename_match",
                            "matched_files": [
                                doc.meta.get("dl_meta", {})
                                .get("meta", {})
                                .get("origin", {})
                                .get("filename", "")
                                for doc in matching_docs
                            ],
                        }
                    )
                    logger.info(
                        f"Removed {len(matching_docs)} documents for filename: {filename}"
                    )
                else:
                    removed_files.append(
                        {
                            "file_name": filename,
                            "documents_removed": 0,
                            "method": "filename_match",
                            "note": "No documents found",
                        }
                    )

            except Exception as e:
                error_msg = (
                    f"Error removing documents for filename '{filename}': {str(e)}"
                )
                errors.append(error_msg)
                logger.error(error_msg)

        return {
            "success": True,
            "action": "delete",
            "total_documents_removed": removed_count,
            "index_name": index_name or default_index,
            "hybrid_search_enabled": USE_SPARSE_EMBEDDINGS,
            "removed_files": removed_files,
            "errors": errors if errors else None,
        }

    except Exception as e:
        logger.error(f"Error in delete operation: {e}")
        return {
            "success": False,
            "action": "delete",
            "error": str(e),
            "total_documents_removed": 0,
            "index_name": index_name or default_index,
            "hybrid_search_enabled": USE_SPARSE_EMBEDDINGS,
        }


def get_stats(
    document_store, index_name: str | None, default_index: str
) -> dict[str, Any]:
    """Get document store statistics."""
    try:
        all_docs = document_store.filter_documents()

        total_docs = len(all_docs)

        file_types = {}
        source_types = {}
        files_count = set()
        docs_with_sparse = 0

        for doc in all_docs:
            # prefer flat metadata stamped by DoclingChunker; fall back to dl_meta
            filename = doc.meta.get("filename") or doc.meta.get("file_name", "")
            mimetype = doc.meta.get("mime_type", "unknown")

            if not filename or mimetype == "unknown":
                dl_meta = doc.meta.get("dl_meta", {})
                docling_meta = dl_meta.get("meta", {})
                origin = docling_meta.get("origin", {})
                if not filename:
                    filename = origin.get("filename", "")
                if mimetype == "unknown":
                    mimetype = origin.get("mimetype", "unknown")

            if hasattr(doc, "sparse_embedding") and doc.sparse_embedding is not None:
                docs_with_sparse += 1

            if filename:
                ext = Path(filename).suffix.lower() or "no_extension"
                file_types[ext] = file_types.get(ext, 0) + 1
                files_count.add(filename)

            source_types[mimetype] = source_types.get(mimetype, 0) + 1

        return {
            "success": True,
            "action": "stats",
            "total_documents": total_docs,
            "total_files": len(files_count),
            "documents_with_sparse_embeddings": docs_with_sparse,
            "file_extensions": dict(sorted(file_types.items())),
            "mimetypes": dict(sorted(source_types.items())),
            "index_name": index_name or default_index,
            "embedding_dimension": EMBEDDING_DIM,
            "hybrid_search_enabled": document_store.use_sparse_embeddings,
        }

    except Exception as e:
        logger.error(f"Error getting stats: {e}")
        return {
            "success": False,
            "action": "stats",
            "error": str(e),
            "index_name": index_name or default_index,
            "hybrid_search_enabled": USE_SPARSE_EMBEDDINGS,
        }


def get_file_content(
    document_store,
    file_name: str | None,
    index_name: str | None,
    default_index: str,
    file_id: str | None = None,
) -> dict[str, Any]:
    """Reassemble the full parsed content of a file from its chunks."""
    if not file_id and not file_name:
        return {
            "success": False,
            "action": "get_file_content",
            "error": "file_id or file_name parameter is required",
            "index_name": index_name or default_index,
        }

    lookup_label = file_id or file_name

    try:
        # server-side filter avoids loading the entire collection
        if file_id:
            filters = {
                "operator": "==",
                "field": "meta.file_id",
                "value": file_id,
            }
            matching_docs = document_store.filter_documents(filters=filters)
        elif file_name:
            filters = {
                "operator": "==",
                "field": "meta.filename",
                "value": file_name,
            }
            matching_docs = document_store.filter_documents(filters=filters)

            # fallback to basename match (covers full-path stored filenames)
            if not matching_docs:
                all_docs = document_store.filter_documents()
                matching_docs = []
                for doc in all_docs:
                    doc_filename = doc.meta.get("filename") or doc.meta.get(
                        "file_name", ""
                    )
                    if not doc_filename:
                        dl_meta = doc.meta.get("dl_meta", {})
                        docling_meta = dl_meta.get("meta", {})
                        origin = docling_meta.get("origin", {})
                        doc_filename = origin.get("filename", "")
                    if Path(doc_filename).name == file_name:
                        matching_docs.append(doc)
        else:
            matching_docs = []

        if not matching_docs:
            logger.warning(
                "No documents matched for lookup=%s in index=%s (file_id=%s, file_name=%s)",
                lookup_label,
                index_name or default_index,
                file_id,
                file_name,
            )
            return {
                "success": False,
                "action": "get_file_content",
                "error": f"No documents found for file: {lookup_label}",
                "file_name": file_name,
                "index_name": index_name or default_index,
            }

        matching_docs.sort(key=lambda d: d.meta.get("chunk_index", 0))

        content = "\n\n".join(doc.content for doc in matching_docs if doc.content)

        return {
            "success": True,
            "action": "get_file_content",
            "file_name": file_name,
            "total_chunks": len(matching_docs),
            "content": content,
            "index_name": index_name or default_index,
        }

    except Exception as e:
        logger.error(f"Error getting file content for '{lookup_label}': {e}")
        return {
            "success": False,
            "action": "get_file_content",
            "error": str(e),
            "file_name": file_name,
            "index_name": index_name or default_index,
        }


def delete_index(
    get_document_store_fn,
    get_stats_fn,
    document_stores_cache: dict,
    index_name: str,
    confirm_deletion: bool,
    default_index: str,
) -> dict[str, Any]:
    """Delete an entire index/collection."""
    if not confirm_deletion:
        return {
            "success": False,
            "action": "delete_index",
            "error": "Index deletion requires explicit confirmation. Set confirm_index_deletion=true",
            "index_name": index_name,
            "warning": "This action will permanently delete the entire index and all its documents",
            "hybrid_search_enabled": USE_SPARSE_EMBEDDINGS,
        }

    if index_name == default_index:
        logger.warning(f"Attempting to delete default index: {index_name}")

    try:
        document_store = get_document_store_fn(index_name)

        stats_before = get_stats_fn(document_store, index_name)
        total_docs_before = stats_before.get("total_documents", 0)
        total_files_before = stats_before.get("total_files", 0)

        # need the underlying Qdrant client
        document_store._initialize_client()

        if not document_store._client.collection_exists(index_name):
            return {
                "success": False,
                "action": "delete_index",
                "error": f"Index '{index_name}' does not exist",
                "index_name": index_name,
                "hybrid_search_enabled": USE_SPARSE_EMBEDDINGS,
            }

        logger.info(f"Deleting index '{index_name}' with {total_docs_before} documents")

        document_store._client.delete_collection(index_name)

        if index_name in document_stores_cache:
            del document_stores_cache[index_name]

        logger.info(f"Successfully deleted index: {index_name}")

        return {
            "success": True,
            "action": "delete_index",
            "index_name": index_name,
            "documents_deleted": total_docs_before,
            "files_deleted": total_files_before,
            "message": f"Index '{index_name}' has been completely deleted",
            "hybrid_search_enabled": USE_SPARSE_EMBEDDINGS,
        }

    except Exception as e:
        logger.error(f"Error deleting index '{index_name}': {e}")
        return {
            "success": False,
            "action": "delete_index",
            "error": str(e),
            "index_name": index_name,
            "hybrid_search_enabled": USE_SPARSE_EMBEDDINGS,
        }
