"""
Embedding engine for Sigil.
Uses fastembed (CPU-only, no GPU required) for dense retrieval.
Falls back to keyword-only if fastembed not installed.
"""

import struct
import hashlib
from typing import Optional

_model = None
_model_name = None


def _get_model(model_name: str = "BAAI/bge-small-en-v1.5"):
    """Lazy-load the embedding model. Only loaded once."""
    global _model, _model_name
    if _model is not None and _model_name == model_name:
        return _model
    try:
        from fastembed import TextEmbedding
        _model = TextEmbedding(model_name=model_name)
        _model_name = model_name
        return _model
    except ImportError:
        return None


def embed(text: str, model_name: str = "BAAI/bge-small-en-v1.5") -> Optional[bytes]:
    """
    Embed text into a dense vector, returned as bytes.
    Returns None if fastembed is not installed.
    """
    model = _get_model(model_name)
    if model is None:
        return None
    embeddings = list(model.embed([text]))
    if not embeddings:
        return None
    vec = embeddings[0]
    return struct.pack(f"{len(vec)}f", *vec)


def embed_batch(texts: list[str], model_name: str = "BAAI/bge-small-en-v1.5") -> list[Optional[bytes]]:
    """Embed multiple texts in one batch call."""
    model = _get_model(model_name)
    if model is None:
        return [None] * len(texts)
    embeddings = list(model.embed(texts))
    results = []
    for vec in embeddings:
        results.append(struct.pack(f"{len(vec)}f", *vec))
    return results


def cosine_similarity(a: bytes, b: bytes) -> float:
    """Compute cosine similarity between two embedding blobs."""
    n = len(a) // 4
    va = struct.unpack(f"{n}f", a)
    vb = struct.unpack(f"{n}f", b)
    dot = sum(x * y for x, y in zip(va, vb))
    norm_a = sum(x * x for x in va) ** 0.5
    norm_b = sum(x * x for x in vb) ** 0.5
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def embedding_dimensions(model_name: str = "BAAI/bge-small-en-v1.5") -> int:
    """Return the embedding dimensions for a model."""
    dims = {
        "BAAI/bge-small-en-v1.5": 384,
        "BAAI/bge-base-en-v1.5": 768,
        "sentence-transformers/all-MiniLM-L6-v2": 384,
    }
    return dims.get(model_name, 384)


def text_hash(text: str) -> str:
    """Quick content hash for dedup."""
    return hashlib.sha256(text.encode()).hexdigest()[:16]


def has_embeddings() -> bool:
    """Check if embedding support is available."""
    try:
        from fastembed import TextEmbedding
        return True
    except ImportError:
        return False
