import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.config import settings
from app.llm.llm_client import LLMClient


def main() -> None:
    client = LLMClient()
    print(f"provider={client.provider}")
    print(f"openai_api_mode={settings.openai_api_mode}")
    print(f"configured_openai_base_url={settings.openai_base_url}")
    print(f"effective_openai_base_url={client.openai_base_url}")
    print(f"openai_model={settings.openai_model}")
    print(f"has_openai_api_key={bool(settings.openai_api_key)}")


if __name__ == "__main__":
    main()
