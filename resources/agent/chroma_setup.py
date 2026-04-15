from __future__ import annotations

import argparse
import json
import shutil
import time
from typing import Any

from desktop_agent_lib.vector_store import (
    ProjectChromaStore,
    get_default_collection_name,
    get_project_chroma_path,
)


def _coerce_json_value(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, list):
        return [_coerce_json_value(item) for item in value]
    if isinstance(value, tuple):
        return [_coerce_json_value(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _coerce_json_value(item) for key, item in value.items()}
    return str(value)


def _coerce_metadata(raw_metadata: Any) -> dict[str, Any]:
    if not isinstance(raw_metadata, dict):
        return {}
    return {str(key): _coerce_json_value(value) for key, value in raw_metadata.items()}


def _coerce_embedding(raw_embedding: Any) -> list[float]:
    if not isinstance(raw_embedding, (list, tuple)):
        return []

    embedding: list[float] = []
    for raw_value in raw_embedding:
        try:
            embedding.append(float(raw_value))
        except (TypeError, ValueError):
            embedding.append(0.0)
    return embedding


def _build_relative_embedding(embedding: list[float]) -> tuple[list[float], float]:
    if not embedding:
        return [], 1.0

    max_abs = max(abs(value) for value in embedding)
    if max_abs == 0:
        return [0.0 for _ in embedding], 1.0

    relative_embedding = [round(value / max_abs, 6) for value in embedding]
    return relative_embedding, max_abs


def bootstrap_store() -> dict[str, Any]:
    store = ProjectChromaStore()
    collection = store.get_or_create_collection(
        get_default_collection_name(),
        metadata={"created_by": "blueberry-bootstrap"},
    )

    return {
        "status": "ok",
        "action": "bootstrap",
        "path": str(store.path),
        "collection": getattr(collection, "name", get_default_collection_name()),
        "collections": store.list_collection_names(),
    }


def reset_store() -> dict[str, Any]:
    chroma_path = get_project_chroma_path()
    if chroma_path.exists():
        shutil.rmtree(chroma_path)
    chroma_path.mkdir(parents=True, exist_ok=True)
    (chroma_path / ".gitkeep").write_text("", encoding="utf-8")
    return {
        "status": "ok",
        "action": "reset",
        "path": str(chroma_path),
        "collections": [],
    }


def run_smoke_test() -> dict[str, Any]:
    store = ProjectChromaStore()
    smoke_collection_name = f"{get_default_collection_name()}_smoke_test"

    try:
        collection = store.get_or_create_collection(
            smoke_collection_name,
            metadata={"created_by": "blueberry-smoke-test"},
        )
        collection.upsert(
            ids=["smoke-1", "smoke-2"],
            documents=["Blueberry browser vector search setup", "Chroma smoke test"],
            metadatas=[
                {"kind": "smoke", "created_at": int(time.time())},
                {"kind": "smoke", "created_at": int(time.time())},
            ],
            embeddings=[[0.10, 0.20, 0.30], [0.91, 0.12, 0.18]],
        )
        query_result = collection.query(
            query_embeddings=[[0.11, 0.19, 0.29]],
            n_results=1,
            include=["documents", "metadatas", "distances"],
        )
    finally:
        try:
            store.delete_collection(smoke_collection_name)
        except Exception:
            pass

    return {
        "status": "ok",
        "action": "smoke-test",
        "path": str(store.path),
        "query_result": query_result,
    }


def dump_store_chunks() -> dict[str, Any]:
    store = ProjectChromaStore()
    collection_payloads: list[dict[str, Any]] = []

    for collection_name in store.list_collection_names():
        collection = store.get_or_create_collection(collection_name)
        raw_result = collection.get(include=["documents", "metadatas", "embeddings"])

        raw_ids = raw_result.get("ids") if isinstance(raw_result, dict) else None
        raw_documents = (
            raw_result.get("documents") if isinstance(raw_result, dict) else None
        )
        raw_metadatas = (
            raw_result.get("metadatas") if isinstance(raw_result, dict) else None
        )
        raw_embeddings = (
            raw_result.get("embeddings") if isinstance(raw_result, dict) else None
        )

        ids = raw_ids if isinstance(raw_ids, list) else []
        documents = raw_documents if isinstance(raw_documents, list) else []
        metadatas = raw_metadatas if isinstance(raw_metadatas, list) else []
        embeddings = raw_embeddings if isinstance(raw_embeddings, list) else []

        chunk_count = max(len(ids), len(documents), len(metadatas), len(embeddings))
        chunks: list[dict[str, Any]] = []

        for index in range(chunk_count):
            raw_embedding = embeddings[index] if index < len(embeddings) else []
            embedding = _coerce_embedding(raw_embedding)

            raw_document = documents[index] if index < len(documents) else ""
            if isinstance(raw_document, str):
                document = raw_document
            elif raw_document is None:
                document = ""
            else:
                document = str(raw_document)

            raw_metadata = metadatas[index] if index < len(metadatas) else {}
            metadata = _coerce_metadata(raw_metadata)

            raw_chunk_id = ids[index] if index < len(ids) else None
            chunk_id = raw_chunk_id if isinstance(raw_chunk_id, str) else f"chunk-{index}"

            chunks.append(
                {
                    "id": chunk_id,
                    "document": document,
                    "metadata": metadata,
                    "embedding": embedding,
                    "embedding_dimensions": len(embedding),
                }
            )

        collection_payloads.append(
            {
                "name": collection_name,
                "chunk_count": len(chunks),
                "chunks": chunks,
            }
        )

    total_chunks = sum(
        collection_payload.get("chunk_count", 0) for collection_payload in collection_payloads
    )

    return {
        "status": "ok",
        "action": "dump",
        "path": str(store.path),
        "default_collection": get_default_collection_name(),
        "collection_count": len(collection_payloads),
        "total_chunks": total_chunks,
        "collections": collection_payloads,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Bootstrap and verify the local Chroma store.")
    parser.add_argument(
        "--bootstrap",
        action="store_true",
        help="Create the persistent Chroma folder and default collection.",
    )
    parser.add_argument(
        "--smoke-test",
        action="store_true",
        help="Run a local upsert/query smoke test against the Chroma store.",
    )
    parser.add_argument(
        "--reset",
        action="store_true",
        help="Delete all collections from the local Chroma store.",
    )
    parser.add_argument(
        "--dump",
        action="store_true",
        help="Return all stored chunks with embeddings and metadata.",
    )
    args = parser.parse_args()

    if args.reset:
        result = reset_store()
    elif args.smoke_test:
        result = run_smoke_test()
    elif args.dump:
        result = dump_store_chunks()
    else:
        result = bootstrap_store()

    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()

