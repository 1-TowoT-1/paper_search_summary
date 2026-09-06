import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.config import settings


def main() -> None:
    print(f"PDF_OCR_ENABLED={settings.pdf_ocr_enabled}")
    print(f"PDF_OCR_PROVIDER={settings.pdf_ocr_provider}")
    print(f"PDF_OCR_LANGUAGES={settings.pdf_ocr_languages}")
    print(f"TESSERACT_CMD={settings.tesseract_cmd}")
    print(f"PDF_MULTIMODAL_ENABLED={settings.pdf_multimodal_enabled}")
    print(f"PDF_MULTIMODAL_MODEL={settings.pdf_multimodal_model or settings.openai_model}")


if __name__ == "__main__":
    main()
