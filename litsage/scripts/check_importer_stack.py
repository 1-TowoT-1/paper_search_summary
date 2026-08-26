import importlib.util
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.config import settings


def module_available(name: str) -> bool:
    return importlib.util.find_spec(name) is not None


def main() -> None:
    print(f"embedding_provider={settings.embedding_provider}")
    print(f"embedding_dim={settings.embedding_dim}")
    print(f"bge_url={settings.bge_base_url.rstrip('/')}/{settings.bge_embedding_path.strip('/')}")
    print(f"bge_request_format={settings.bge_request_format}")
    print(f"milvus_uri={settings.milvus_uri}")
    print(f"abstract_collection={settings.abstract_collection}")
    print(f"chunk_collection={settings.chunk_collection}")
    print(f"pymilvus_available={module_available('pymilvus')}")
    print(f"fitz_available={module_available('fitz')}")
    print(f"httpx_available={module_available('httpx')}")


if __name__ == "__main__":
    main()

