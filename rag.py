"""
RAG utilities — embedding via Ollama + vector search via Pinecone.

Embedding model runs locally through Ollama (no extra API costs).
Pinecone stores document chunks and handles similarity search.
"""

import os
import requests

# ── Config (loaded from env / .env) ─────────────────────────────────────────
OLLAMA_BASE_URL = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")
EMBED_MODEL = os.environ.get("EMBED_MODEL", "nomic-embed-text")

# Lazy-initialized Pinecone index (created on first use)
_pinecone_index = None


def _get_pinecone_index():
    """Return a cached Pinecone Index object, or None if not configured."""
    global _pinecone_index
    if _pinecone_index is not None:
        return _pinecone_index

    api_key = os.environ.get("PINECONE_API_KEY")
    index_name = os.environ.get("PINECONE_INDEX_NAME")

    if not api_key or not index_name:
        return None

    from pinecone import Pinecone

    pc = Pinecone(api_key=api_key)
    _pinecone_index = pc.Index(index_name)
    return _pinecone_index


# ── Embedding ───────────────────────────────────────────────────────────────


def get_embedding(text: str) -> list[float]:
    """Get a vector embedding from Ollama's local embedding model.

    Uses the /api/embed endpoint (Ollama ≥ 0.4).
    Make sure the model is pulled first:  ollama pull nomic-embed-text
    """
    resp = requests.post(
        f"{OLLAMA_BASE_URL}/api/embed",
        json={"model": EMBED_MODEL, "input": text},
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()["embeddings"][0]


# ── Search ──────────────────────────────────────────────────────────────────


def search_context(
    query: str,
    top_k: int = 3,
    score_threshold: float = 0.5,
) -> list[str]:
    """Embed the query and return matching document chunks from Pinecone.

    Returns an empty list if Pinecone is not configured or no matches
    exceed the score threshold.
    """
    index = _get_pinecone_index()
    if index is None:
        return []

    embedding = get_embedding(query)
    results = index.query(
        vector=embedding,
        top_k=top_k,
        include_metadata=True,
    )

    chunks: list[str] = []
    for match in results.get("matches", []):
        if match["score"] >= score_threshold:
            text = match.get("metadata", {}).get("text", "")
            if text:
                chunks.append(text)

    return chunks
