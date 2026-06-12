from typing import Any

from config import (
    EMBEDDING_DIM,
    QDRANT_HNSW_CONFIG,
    QDRANT_INDEX,
    QDRANT_URL,
    USE_SPARSE_EMBEDDINGS,
)
from hayhooks import BasePipelineWrapper
from haystack_integrations.document_stores.qdrant import QdrantDocumentStore
from loguru import logger

from .operations import (
    delete_documents,
    delete_index,
    get_file_content,
    get_stats,
    list_files,
)


class DocumentManagementPipelineWrapper(BasePipelineWrapper):
    """Document management operations (list, delete, stats)."""

    def setup(self) -> None:
        self._document_stores = {}
        self._default_index = QDRANT_INDEX

        self.document_store = self._get_document_store()
        logger.info(
            f"Connected to default document store with sparse embeddings: {USE_SPARSE_EMBEDDINGS}"
        )

    def _get_document_store(self, index_name: str = None) -> QdrantDocumentStore:
        if index_name is None:
            index_name = self._default_index

        if index_name not in self._document_stores:
            logger.info(
                f"Creating document store for index: {index_name} with sparse embeddings: {USE_SPARSE_EMBEDDINGS}"
            )
            self._document_stores[index_name] = QdrantDocumentStore(
                url=QDRANT_URL,
                index=index_name,
                embedding_dim=EMBEDDING_DIM,
                recreate_index=False,
                use_sparse_embeddings=USE_SPARSE_EMBEDDINGS,
                hnsw_config=QDRANT_HNSW_CONFIG,
            )

        return self._document_stores[index_name]

    def run_api(
        self,
        action: str,
        file_paths: list[str] | None = None,
        file_names: list[str] | None = None,
        index_name: str | None = None,
        confirm_index_deletion: bool = False,
        file_name: str | None = None,
        file_id: str | None = None,
        file_ids: list[str] | None = None,
    ) -> dict[str, Any]:
        """Document management API.

        :param action: 'list', 'delete', 'stats', or 'get_file_content'.
        :param file_id: file UUID, preferred over file_name for get_file_content.
        :param file_ids: stable meta.file_id values for rename-proof delete.
        """
        try:
            # delete with index_name but no file selectors targets the whole index
            is_index_deletion = (
                action == "delete"
                and index_name is not None
                and not file_paths
                and not file_names
                and not file_ids
            )

            if is_index_deletion:
                return delete_index(
                    self._get_document_store,
                    lambda ds, idx: get_stats(ds, idx, self._default_index),
                    self._document_stores,
                    index_name,
                    confirm_index_deletion,
                    self._default_index,
                )

            document_store = self._get_document_store(index_name)

            if action == "list":
                return list_files(document_store, index_name, self._default_index)
            elif action == "delete":
                return delete_documents(
                    document_store,
                    file_paths,
                    file_names,
                    index_name,
                    self._default_index,
                    file_ids=file_ids,
                )
            elif action == "stats":
                return get_stats(document_store, index_name, self._default_index)
            elif action == "get_file_content":
                return get_file_content(
                    document_store, file_name, index_name, self._default_index, file_id
                )
            else:
                return {
                    "success": False,
                    "error": f"Unknown action: {action}. Valid actions: list, delete, stats, get_file_content",
                    "index_name": index_name or self._default_index,
                    "hybrid_search_enabled": USE_SPARSE_EMBEDDINGS,
                }
        except Exception as e:
            logger.error(f"Error in document management action '{action}': {e}")
            return {
                "success": False,
                "error": str(e),
                "index_name": index_name or self._default_index,
                "hybrid_search_enabled": USE_SPARSE_EMBEDDINGS,
            }

    async def run_api_async(
        self,
        action: str,
        file_paths: list[str] | None = None,
        file_names: list[str] | None = None,
        index_name: str | None = None,
        confirm_index_deletion: bool = False,
        file_name: str | None = None,
        file_id: str | None = None,
        file_ids: list[str] | None = None,
    ) -> dict[str, Any]:
        return self.run_api(
            action,
            file_paths,
            file_names,
            index_name,
            confirm_index_deletion,
            file_name,
            file_id,
            file_ids,
        )


PipelineWrapper = DocumentManagementPipelineWrapper
