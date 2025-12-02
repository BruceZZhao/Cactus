"""RAG encoding script to build vector database from character profiles."""
import os
from typing import List, Dict
from pathlib import Path

from transformers import AutoTokenizer
from sentence_transformers import SentenceTransformer
from qdrant_client.local.qdrant_local import QdrantLocal
from qdrant_client.http.models import Distance, VectorParams, PointStruct

from backend.rag.qdrant_path import QDRANT_LOCATION

os.environ["TOKENIZERS_PARALLELISM"] = "false"


def load_and_chunk_single_pass(
    filepath: str,
    chunk_size: int = 100,
    overlap: int = 20,
    max_tokens: int = 256,
    ) -> List[Dict]:
    """Token-based sliding window chunker."""
    tokenizer = AutoTokenizer.from_pretrained(
        "sentence-transformers/all-MiniLM-L6-v2", use_fast=True
    )

    file = Path(filepath)
    if not file.exists():
        raise FileNotFoundError(f"File not found: {filepath}")

    text = file.read_text(encoding="utf-8")
    paragraphs = [p.strip() for p in text.split("\n") if p.strip()]

    chunks: List[Dict] = []
    chunk_index = 0

    window = min(chunk_size, max_tokens)
    step = max(1, chunk_size - overlap)

    for para_idx, para in enumerate(paragraphs):
        input_ids = tokenizer(para, add_special_tokens=False).input_ids

        start = 0
        while start < len(input_ids):
            end = min(start + window, len(input_ids))
            token_slice = input_ids[start:end]

            chunk_text = tokenizer.decode(
                token_slice,
                skip_special_tokens=True,
                clean_up_tokenization_spaces=True,
            ).strip()

            if chunk_text:
                chunks.append(
                    {
                        "index": chunk_index,
                        "chunk_text": chunk_text,
                        "paragraph_index": para_idx,
                        "full_paragraph": para,
                    }
                )
                chunk_index += 1

            if end == len(input_ids):
                break
            start += step

    return chunks


def build_collection(
    client: QdrantLocal,
    collection_name: str,
    filepath: str,
    embed_model: SentenceTransformer,
    chunk_size: int = 100,
    overlap: int = 20,
    max_tokens: int = 256,
):
    """Build a Qdrant collection from a text file."""
    client.recreate_collection(
        collection_name=collection_name,
        vectors_config=VectorParams(size=384, distance=Distance.COSINE),
    )

    chunks = load_and_chunk_single_pass(
        filepath=filepath, chunk_size=chunk_size, overlap=overlap, max_tokens=max_tokens
    )

    if not chunks:
        print(f"No chunks produced for {filepath}. Skipping.")
        return

    # Generate embeddings
    texts = [c["chunk_text"] for c in chunks]
    vectors = embed_model.encode(texts, convert_to_numpy=False)
    vectors = [v.tolist() for v in vectors]

    # Insert into Qdrant
    points = []
    for i, chunk in enumerate(chunks):
        points.append(
            PointStruct(
                id=chunk["index"],
                vector=vectors[i],
                payload={
                    "chunk": chunk["chunk_text"],
                    "index": chunk["index"],
                    "paragraph_index": chunk["paragraph_index"],
                    "full_paragraph": chunk["full_paragraph"],
                },
            )
        )

    client.upsert(collection_name=collection_name, points=points)
    print(f"{len(chunks)} chunks inserted into {collection_name} from {filepath}")


def print_dir_tree(root: Path, max_depth: int = 3):
    """Print directory tree structure."""
    root = root.resolve()
    print(f"\n📁 Qdrant data directory: {root}")
    for current_root, dirs, files in os.walk(root):
        depth = Path(current_root).relative_to(root).parts
        if len(depth) > max_depth:
            continue
        indent = "    " * len(depth)
        print(f"{indent}{Path(current_root).name}/")
        for f in files:
            print(f"{indent}    {f}")


if __name__ == "__main__":
    project_root = Path(__file__).resolve().parent.parent
    qdrant_path = Path(QDRANT_LOCATION)
    qdrant_path.mkdir(parents=True, exist_ok=True)

    # Initialize embedding model
    embed_model = SentenceTransformer("all-MiniLM-L6-v2", device="cpu")
    embed_model.max_seq_length = 256

    # Initialize Qdrant client
    client = QdrantLocal(location=str(qdrant_path))

    # Build vector collections for profiles
    profile_dir = project_root / "rag" / "profiles"
    profile_dir.mkdir(parents=True, exist_ok=True)
    
    jobs = [
        ("default_profile", str(profile_dir / "default_profile")),
        # Add more profiles as needed
    ]

    for collection_name, filepath in jobs:
        if Path(filepath).exists():
            build_collection(
                client=client,
                collection_name=collection_name,
                filepath=filepath,
                embed_model=embed_model,
                chunk_size=100,
                overlap=20,
                max_tokens=256,
            )
        else:
            print(f"Profile file not found: {filepath}, skipping...")

    # Print data directory structure
    print_dir_tree(qdrant_path, max_depth=3)

