"""Real local embedding model via Sentence Transformers (no API key, no mock fallback)."""
from typing import Protocol

from sentence_transformers import SentenceTransformer


class Embedder(Protocol):
    model_name: str
    dimensions: int

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        """Return one vector per input text, in the same order."""
        ...

    def embed_query(self, question: str) -> list[float]:
        """Return a query vector compatible with the stored document vectors."""
        ...


class MyEmbedder:
    """Default model: intfloat/multilingual-e5-small (384 dims, max 512 tokens).

    E5 models are trained with prefixes: "query: " for questions, "passage: " for documents.
    """

    def __init__(self, model_name: str) -> None:
        if not model_name:
            raise ValueError("EMBEDDING_MODEL is empty; set it in starter/.env")
        self.model_name = model_name
        self.model = SentenceTransformer(model_name)  # raises if the model cannot be loaded
        get_dim = getattr(self.model, "get_embedding_dimension", None) \
            or self.model.get_sentence_embedding_dimension  # renamed in sentence-transformers 6
        self.dimensions = get_dim()
        self.max_tokens = self.model.max_seq_length
        is_e5 = "e5" in model_name.lower()
        self.query_prefix = "query: " if is_e5 else ""
        self.doc_prefix = "passage: " if is_e5 else ""

    def count_truncated(self, texts: list[str]) -> int:
        """How many texts (with prefix) exceed the model's token limit and would be cut."""
        tok = self.model.tokenizer
        return sum(len(tok(self.doc_prefix + t)["input_ids"]) > self.max_tokens for t in texts)

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return self.model.encode([self.doc_prefix + t for t in texts], batch_size=32,
                                 normalize_embeddings=True, show_progress_bar=True).tolist()

    def embed_query(self, question: str) -> list[float]:
        return self.model.encode([self.query_prefix + question],
                                 normalize_embeddings=True)[0].tolist()
