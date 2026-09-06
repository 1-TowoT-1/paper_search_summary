from dataclasses import dataclass
from uuid import UUID

from app.config import settings

try:
    from pymilvus import DataType, MilvusClient
except ImportError:  # pragma: no cover
    DataType = None
    MilvusClient = None


@dataclass
class VectorHit:
    paper_id: UUID
    score: float
    chunk_id: str | None = None
    text: str | None = None
    locator: str | None = None


class VectorStoreError(RuntimeError):
    pass


class VectorStore:
    def __init__(self) -> None:
        if MilvusClient is None or DataType is None:
            raise VectorStoreError("pymilvus is not installed. Run `pip install -r requirements.txt`.")
        self.client = MilvusClient(uri=settings.milvus_uri)
        self._ensure_collections()

    async def upsert_paper_abstract(self, paper_id: UUID, vector: list[float], metadata: dict) -> None:
        self._validate_vector(vector)
        self.client.upsert(
            collection_name=settings.abstract_collection,
            data=[
                {
                    "id": str(paper_id),
                    "paper_id": str(paper_id),
                    "vector": vector,
                    "title": str(metadata.get("title") or "")[:1024],
                    "source": str(metadata.get("source") or "")[:64],
                    "source_id": str(metadata.get("source_id") or "")[:128],
                    "published_date": str(metadata.get("published_date") or "")[:32],
                }
            ],
        )

    async def upsert_chunk(self, paper_id: UUID, chunk_id: str, vector: list[float], text: str, metadata: dict) -> None:
        self._validate_vector(vector)
        self.client.upsert(
            collection_name=settings.chunk_collection,
            data=[
                {
                    "id": chunk_id,
                    "paper_id": str(paper_id),
                    "vector": vector,
                    "text": text[:8192],
                    "title": str(metadata.get("title") or "")[:1024],
                    "source": str(metadata.get("source") or "")[:64],
                    "source_id": str(metadata.get("source_id") or "")[:128],
                    "locator": str(metadata.get("locator") or "")[:128],
                    "user_id": str(metadata.get("user_id") or "")[:64],
                    "project_id": str(metadata.get("project_id") or "")[:64],
                    "source_type": str(metadata.get("source_type") or "")[:64],
                    "publication_status": str(metadata.get("publication_status") or "")[:64],
                    "visibility": str(metadata.get("visibility") or "")[:64],
                    "chunk_type": str(metadata.get("chunk_type") or "")[:64],
                }
            ],
        )

    async def search_abstracts(self, vector: list[float], limit: int) -> list[VectorHit]:
        self._validate_vector(vector)
        results = self.client.search(
            collection_name=settings.abstract_collection,
            data=[vector],
            limit=limit,
            output_fields=["paper_id"],
        )
        return self._to_hits(results)

    async def search_chunks(self, vector: list[float], paper_ids: list[UUID], limit: int = 10) -> list[VectorHit]:
        self._validate_vector(vector)
        filter_expr = ""
        if paper_ids:
            quoted_ids = ", ".join(f'"{paper_id}"' for paper_id in paper_ids)
            filter_expr = f"paper_id in [{quoted_ids}]"

        results = self.client.search(
            collection_name=settings.chunk_collection,
            data=[vector],
            limit=limit,
            filter=filter_expr,
            output_fields=["paper_id", "text", "title", "locator"],
        )
        return self._to_hits(results)

    async def has_paper_chunks(self, paper_id: UUID) -> bool:
        if not self.client.has_collection(settings.chunk_collection):
            return False
        results = self.client.query(
            collection_name=settings.chunk_collection,
            filter=f'paper_id == "{paper_id}"',
            output_fields=["id"],
            limit=1,
        )
        return bool(results)

    async def delete_paper_vectors(self, paper_id: UUID) -> dict[str, int | str]:
        paper_id_value = str(paper_id)
        filter_expr = f'paper_id == "{paper_id_value}"'
        abstract_result = self._delete_by_filter(settings.abstract_collection, filter_expr)
        chunk_result = self._delete_by_filter(settings.chunk_collection, filter_expr)
        return {
            "paper_id": paper_id_value,
            "abstract_collection": settings.abstract_collection,
            "chunk_collection": settings.chunk_collection,
            "abstract_deleted": self._deleted_count(abstract_result),
            "chunks_deleted": self._deleted_count(chunk_result),
        }

    async def delete_paper_chunks(self, paper_id: UUID) -> int:
        result = self._delete_by_filter(settings.chunk_collection, f'paper_id == "{paper_id}"')
        return self._deleted_count(result)

    def _ensure_collections(self) -> None:
        self._ensure_abstract_collection()
        self._ensure_chunk_collection()

    def _ensure_abstract_collection(self) -> None:
        if self.client.has_collection(settings.abstract_collection):
            return

        schema = MilvusClient.create_schema(auto_id=False, enable_dynamic_field=True)
        schema.add_field("id", DataType.VARCHAR, is_primary=True, max_length=64)
        schema.add_field("paper_id", DataType.VARCHAR, max_length=64)
        schema.add_field("vector", DataType.FLOAT_VECTOR, dim=settings.embedding_dim)
        schema.add_field("title", DataType.VARCHAR, max_length=1024)
        schema.add_field("source", DataType.VARCHAR, max_length=64)
        schema.add_field("source_id", DataType.VARCHAR, max_length=128)
        schema.add_field("published_date", DataType.VARCHAR, max_length=32)

        index_params = self.client.prepare_index_params()
        index_params.add_index(
            field_name="vector",
            index_type="AUTOINDEX",
            metric_type=settings.milvus_metric_type,
        )
        self.client.create_collection(
            collection_name=settings.abstract_collection,
            schema=schema,
            index_params=index_params,
        )

    def _ensure_chunk_collection(self) -> None:
        if self.client.has_collection(settings.chunk_collection):
            return

        schema = MilvusClient.create_schema(auto_id=False, enable_dynamic_field=True)
        schema.add_field("id", DataType.VARCHAR, is_primary=True, max_length=128)
        schema.add_field("paper_id", DataType.VARCHAR, max_length=64)
        schema.add_field("vector", DataType.FLOAT_VECTOR, dim=settings.embedding_dim)
        schema.add_field("text", DataType.VARCHAR, max_length=8192)
        schema.add_field("title", DataType.VARCHAR, max_length=1024)
        schema.add_field("source", DataType.VARCHAR, max_length=64)
        schema.add_field("source_id", DataType.VARCHAR, max_length=128)
        schema.add_field("locator", DataType.VARCHAR, max_length=128)

        index_params = self.client.prepare_index_params()
        index_params.add_index(
            field_name="vector",
            index_type="AUTOINDEX",
            metric_type=settings.milvus_metric_type,
        )
        self.client.create_collection(
            collection_name=settings.chunk_collection,
            schema=schema,
            index_params=index_params,
        )

    def _validate_vector(self, vector: list[float]) -> None:
        if len(vector) != settings.embedding_dim:
            raise VectorStoreError(f"Expected vector dim {settings.embedding_dim}, got {len(vector)}")

    def _delete_by_filter(self, collection_name: str, filter_expr: str) -> dict:
        if not self.client.has_collection(collection_name):
            return {"delete_count": 0}
        result = self.client.delete(collection_name=collection_name, filter=filter_expr)
        return result if isinstance(result, dict) else {}

    def _deleted_count(self, result: dict) -> int:
        for key in ("delete_count", "delete_cnt", "deleted_count"):
            value = result.get(key)
            if isinstance(value, int):
                return value
        return 0

    def _to_hits(self, results: list) -> list[VectorHit]:
        hits: list[VectorHit] = []
        for result_group in results:
            for item in result_group:
                entity = item.get("entity", {}) if isinstance(item, dict) else {}
                paper_id = entity.get("paper_id")
                if not paper_id:
                    continue
                hits.append(
                    VectorHit(
                        paper_id=UUID(str(paper_id)),
                        score=float(item.get("distance", 0.0)),
                        chunk_id=str(item.get("id")) if item.get("id") else None,
                        text=entity.get("text"),
                        locator=entity.get("locator"),
                    )
                )
        return hits
