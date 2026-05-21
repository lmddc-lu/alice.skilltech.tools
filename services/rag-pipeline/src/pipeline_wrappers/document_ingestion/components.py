from haystack import Document, component
from loguru import logger


@component
class DocumentLogger:
    """Component that logs documents passing through the pipeline."""

    def __init__(self, stage_name: str):
        self.stage_name = stage_name

    @component.output_types(documents=list[Document])
    def run(self, documents: list[Document]) -> dict[str, list[Document]]:
        logger.info(f"[{self.stage_name}] Received {len(documents)} documents")
        for i, doc in enumerate(documents):
            has_embedding = doc.embedding is not None
            embedding_dim = len(doc.embedding) if doc.embedding else 0
            logger.info(
                f"[{self.stage_name}] Doc {i + 1}/{len(documents)}: "
                f"{len(doc.content or '')} chars, "
                f"embedding={'yes' if has_embedding else 'no'}"
                f"{f' (dim={embedding_dim})' if has_embedding else ''}, "
                f"meta={list(doc.meta.keys()) if doc.meta else []}"
            )
        return {"documents": documents}
