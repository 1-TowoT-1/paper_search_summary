import asyncio
from io import BytesIO
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.services.user_material_importer import UserMaterialImporter
from app.config import settings
from app.llm.llm_client import LLMClient
from app.services.user_material_importer import _render_pdf_pages


def write_rendered_pages(path: Path, output_dir: Path) -> None:
    try:
        from PIL import Image
    except ImportError:
        Image = None

    output_dir.mkdir(parents=True, exist_ok=True)
    images = _render_pdf_pages(path, max_pages=settings.pdf_multimodal_max_pages)
    print(f"rendered_images={len(images)}")
    print(f"render_zoom={settings.pdf_render_zoom}")
    print(f"multimodal_max_pages={settings.pdf_multimodal_max_pages}")

    client = LLMClient()
    base_url = settings.generated_image_base_url.rstrip("/")
    namespace = output_dir.name
    for page_number, image_bytes in images:
        image_path = output_dir / f"{path.stem}_page_{page_number}.png"
        image_path.write_bytes(image_bytes)
        width = height = "unknown"
        if Image is not None:
            with Image.open(BytesIO(image_bytes)) as image:
                width, height = image.size
        data_url = client._image_data_url(image_bytes)
        image_url = f"{base_url}/{namespace}/{image_path.name}"
        print(
            f"page={page_number} file={image_path} bytes={len(image_bytes)} "
            f"size={width}x{height} image_url={image_url} data_url_prefix={data_url[:32]}"
        )


async def main() -> None:
    if len(sys.argv) < 2:
        raise SystemExit("Usage: python scripts/debug_pdf_extract.py <pdf_path>")
    path = Path(sys.argv[1])
    output_dir = Path(sys.argv[2]) if len(sys.argv) >= 3 else PROJECT_ROOT / settings.generated_image_dir / "debug_pdf_extract"
    write_rendered_pages(path, output_dir)

    importer = UserMaterialImporter()
    extracted = await importer._extract_pdf(path)
    abstract = importer._extract_declared_abstract(extracted.text)
    print(f"method={extracted.method}")
    print(f"text_length={len(extracted.text)}")
    print(f"pages={len(extracted.pages)}")
    print(f"abstract_length={len(abstract)}")
    print("abstract_preview:")
    print(abstract[:1000])
    print("text_preview:")
    print(extracted.text[:3000])


if __name__ == "__main__":
    asyncio.run(main())
