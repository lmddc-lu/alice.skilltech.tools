import logging
from typing import Any, Protocol, TypedDict

logger = logging.getLogger(__name__)


class Entity(TypedDict):
    type: str
    start: int
    end: int
    score: float
    surface: str


class DetectorProtocol(Protocol):
    model_name: str
    device: str

    def detect(self, text: str, min_score: float = 0.5) -> list[Entity]: ...


class PiiDetector:
    """Thin wrapper around a HuggingFace token-classification pipeline.

    Loading the model is expensive,
    so callers should construct one instance and reuse it. The model has a
    256-token context window; we pass `stride` to the pipeline so longer inputs
    are chunked with overlap and entities aren't truncated at boundaries.
    """

    def __init__(
        self,
        model_name: str,
        device: int | str = -1,
        stride: int = 64,
    ) -> None:
        # Imported lazily so unit tests can run without torch/transformers
        # installed and so the import cost is only paid by the service process.
        from transformers import (
            AutoModelForTokenClassification,
            AutoTokenizer,
            pipeline,
        )

        logger.info("Loading PII model %s on device %s", model_name, device)
        tokenizer = AutoTokenizer.from_pretrained(model_name)
        model = AutoModelForTokenClassification.from_pretrained(model_name)
        self._pipeline: Any = pipeline(
            task="token-classification",
            model=model,
            tokenizer=tokenizer,
            aggregation_strategy="simple",
            device=device,
            stride=stride,
        )
        self.model_name = model_name
        self.device = str(device)
        logger.info("PII model loaded; %d labels", len(model.config.id2label))

    def detect(self, text: str, min_score: float = 0.5) -> list[Entity]:
        if not text or not text.strip():
            return []
        raw = self._pipeline(text)
        entities: list[Entity] = []
        for r in raw:
            score = float(r["score"])
            if score < min_score:
                continue
            start = int(r["start"])
            end = int(r["end"])
            entities.append(
                Entity(
                    type=str(r["entity_group"]),
                    start=start,
                    end=end,
                    score=score,
                    surface=text[start:end],
                )
            )
        entities.sort(key=lambda e: e["start"])
        # Imported here to avoid a circular import (postprocess types from us).
        from pii_filter.postprocess import (
            expand_to_word_boundaries,
            merge_adjacent_spans,
        )

        # Expand subword spans (e.g. "main" -> "Romain") to whole words first,
        # then fuse adjacent fragments.
        entities = expand_to_word_boundaries(entities, text)
        return merge_adjacent_spans(entities, text)
