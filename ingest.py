"""
Document ingestion script — chunk files and upload to Pinecone.

Usage:
    python ingest.py                       # ingest all files in documents/
    python ingest.py --file notes.txt      # ingest a single file
    python ingest.py --dir ./my_docs       # ingest from a custom directory

Supported formats: .txt, .md

Prerequisites:
    1. Set PINECONE_API_KEY in .env
    2. Pull the embedding model:  ollama pull nomic-embed-text
    3. Make sure Ollama is running:  ollama serve
"""

import os
import sys
import argparse
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

from rag import get_embedding  # noqa: E402  (needs env loaded first)

# ── Config ──────────────────────────────────────────────────────────────────
PINECONE_API_KEY = os.environ.get("PINECONE_API_KEY")
PINECONE_INDEX_NAME = os.environ.get("PINECONE_INDEX_NAME", "sama-wellness")
PINECONE_CLOUD = os.environ.get("PINECONE_CLOUD", "aws")
PINECONE_REGION = os.environ.get("PINECONE_REGION", "us-east-1")
EMBED_DIMENSION = int(os.environ.get("EMBED_DIMENSION", "768"))

CHUNK_SIZE = int(os.environ.get("CHUNK_SIZE", "500"))     # characters per chunk
CHUNK_OVERLAP = int(os.environ.get("CHUNK_OVERLAP", "50"))  # overlap between chunks

SUPPORTED_EXTENSIONS = {".txt", ".md"}


# ── Chunking ────────────────────────────────────────────────────────────────


def chunk_text(
    text: str,
    chunk_size: int = CHUNK_SIZE,
    overlap: int = CHUNK_OVERLAP,
) -> list[str]:
    """Split text into overlapping chunks of roughly `chunk_size` characters."""
    chunks: list[str] = []
    start = 0
    while start < len(text):
        end = start + chunk_size
        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)
        start += chunk_size - overlap
    return chunks


# ── Pinecone helpers ────────────────────────────────────────────────────────


def ensure_index(pc, recreate: bool = False):
    """Create the Pinecone index if it does not already exist."""
    existing = [idx.name for idx in pc.list_indexes()]
    if PINECONE_INDEX_NAME in existing:
        if recreate:
            print(f"Deleting existing index '{PINECONE_INDEX_NAME}'...")
            pc.delete_index(PINECONE_INDEX_NAME)
            import time
            time.sleep(3)
        else:
            print(f"Index '{PINECONE_INDEX_NAME}' already exists.")
            return

    from pinecone import ServerlessSpec

    print(f"Creating index '{PINECONE_INDEX_NAME}' "
          f"(dim={EMBED_DIMENSION}, cloud={PINECONE_CLOUD}, region={PINECONE_REGION})...")
    pc.create_index(
        name=PINECONE_INDEX_NAME,
        dimension=EMBED_DIMENSION,
        metric="cosine",
        spec=ServerlessSpec(cloud=PINECONE_CLOUD, region=PINECONE_REGION),
    )
    print("Index created. Waiting for it to be ready...")
    # Pinecone serverless indexes are usually ready within seconds
    import time
    time.sleep(5)
    print("Done.")


def ingest_file(index, file_path: Path):
    """Read → chunk → embed → upsert a single file into Pinecone."""
    print(f"\nIngesting: {file_path}")

    text = file_path.read_text(encoding="utf-8")
    chunks = chunk_text(text)
    print(f"  {len(chunks)} chunk(s)")

    vectors = []
    for i, chunk in enumerate(chunks):
        vec_id = f"{file_path.stem}_{i}"
        embedding = get_embedding(chunk)
        vectors.append({
            "id": vec_id,
            "values": embedding,
            "metadata": {
                "text": chunk,
                "source": file_path.name,
                "chunk_index": i,
            },
        })
        if (i + 1) % 10 == 0:
            print(f"  Embedded {i + 1}/{len(chunks)}")

    # Upsert in batches of 100
    BATCH = 100
    for i in range(0, len(vectors), BATCH):
        batch = vectors[i : i + BATCH]
        index.upsert(vectors=batch)

    print(f"  Upserted {len(vectors)} vectors")


# ── CLI ─────────────────────────────────────────────────────────────────────


def main():
    parser = argparse.ArgumentParser(description="Ingest documents into Pinecone for RAG")
    parser.add_argument("--file", type=str, help="Path to a specific file")
    parser.add_argument("--dir", type=str, default="documents",
                        help="Directory containing documents (default: documents/)")
    parser.add_argument("--recreate", action="store_true",
                        help="Delete and recreate the Pinecone index (use when dimension changed)")
    args = parser.parse_args()

    if not PINECONE_API_KEY:
        print("ERROR: PINECONE_API_KEY not set. Add it to your .env file.")
        sys.exit(1)

    from pinecone import Pinecone

    pc = Pinecone(api_key=PINECONE_API_KEY)
    ensure_index(pc, recreate=args.recreate)
    index = pc.Index(PINECONE_INDEX_NAME)

    if args.file:
        path = Path(args.file)
        if not path.exists():
            print(f"File not found: {path}")
            sys.exit(1)
        ingest_file(index, path)
    else:
        doc_dir = Path(args.dir)
        if not doc_dir.exists():
            print(f"Directory '{doc_dir}/' not found.")
            print("Create a 'documents/' folder and add .txt or .md files.")
            sys.exit(1)

        files = sorted(f for f in doc_dir.iterdir() if f.suffix in SUPPORTED_EXTENSIONS)
        if not files:
            print(f"No supported files in {doc_dir}/  (expected: {', '.join(SUPPORTED_EXTENSIONS)})")
            sys.exit(1)

        print(f"Found {len(files)} file(s) to ingest\n")
        for f in files:
            ingest_file(index, f)

    print("\nIngestion complete!")


if __name__ == "__main__":
    main()
