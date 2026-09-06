import argparse
import asyncio
from io import BytesIO
from pathlib import Path
import sys
from uuid import UUID

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import fitz
import httpx

from app.config import settings
from app.llm.llm_client import LLMClient
from app.models.db import Paper, SessionLocal
from app.services.embedding_service import EmbeddingService
from app.services.paper_importer import PaperImporter
from app.services.pdf_resolver import PDFResolver


def _print_step(name: str) -> None:
    print()
    print("=" * 80)
    print(name)
    print("=" * 80)


def _print_config() -> None:
    _print_step("config")
    print(f"OPENAI_BASE_URL={settings.openai_base_url}")
    print(f"OPENAI_API_MODE={settings.openai_api_mode}")
    print(f"OPENAI_MODEL={settings.openai_model}")
    print(f"DEEPSEEK_VISION_MODEL={settings.deepseek_vision_model}")
    print(f"PDF_MULTIMODAL_MODEL={settings.pdf_multimodal_model}")
    print(f"EFFECTIVE_VISION_MODEL={LLMClient()._vision_model()}")
    print(f"PDF_MULTIMODAL_ENABLED={settings.pdf_multimodal_enabled}")
    print(f"PDF_MULTIMODAL_IMAGE_TRANSPORT={settings.pdf_multimodal_image_transport}")
    print(f"PDF_MULTIMODAL_MAX_PAGES={settings.pdf_multimodal_max_pages}")
    print(f"PDF_RENDER_ZOOM={settings.pdf_render_zoom}")
    print(f"EMBEDDING_PROVIDER={settings.embedding_provider}")
    print(f"EMBEDDING_MODEL={settings.embedding_model}")
    print(f"EMBEDDING_DIM={settings.embedding_dim}")


def _paper_pdf_url(paper_id: str) -> tuple[str, str]:
    db = SessionLocal()
    try:
        paper = db.get(Paper, UUID(paper_id))
        if not paper:
            raise SystemExit(f"Paper not found: {paper_id}")
        if not paper.pdf_url:
            raise SystemExit(f"Paper has no pdf_url: {paper_id}")
        print(f"paper_id={paper.id}")
        print(f"title={paper.title}")
        print(f"source={paper.source}")
        print(f"source_id={paper.source_id}")
        print(f"pdf_url={paper.pdf_url}")
        return paper.pdf_url, f"{paper.source}-{paper.source_id}.pdf"
    finally:
        db.close()


async def _load_pdf_bytes(args: argparse.Namespace) -> tuple[bytes, str]:
    _print_step("load pdf")
    if args.paper_id:
        pdf_url, filename = _paper_pdf_url(args.paper_id)
        return await _download_pdf(pdf_url), filename
    if args.pdf_url:
        return await _download_pdf(args.pdf_url), Path(args.pdf_url).name or "remote.pdf"
    if args.file:
        path = Path(args.file)
        data = path.read_bytes()
        print(f"file={path}")
        print(f"bytes={len(data)}")
        return data, path.name
    raise SystemExit("Provide --paper-id, --pdf-url, or --file")


async def _try_structured_full_text_from_source(args: argparse.Namespace) -> str:
    importer = PaperImporter()
    pmc_id = None
    if args.pmc_id:
        pmc_id = args.pmc_id
    elif args.pdf_url:
        pmc_id = importer._pmc_id_from_url(args.pdf_url)
    elif args.paper_id:
        db = SessionLocal()
        try:
            paper = db.get(Paper, UUID(args.paper_id))
            metadata = paper.metadata_json if paper and isinstance(paper.metadata_json, dict) else {}
            pmc_id = metadata.get("pmc_id")
            if not pmc_id and paper and paper.pdf_url:
                pmc_id = importer._pmc_id_from_url(paper.pdf_url)
        finally:
            db.close()

    if not pmc_id:
        return ""
    return await _test_pmc_structured_full_text(str(pmc_id))


async def _test_pmc_structured_full_text(pmc_id: str) -> str:
    _print_step("pmc structured full text")
    resolver = PDFResolver()
    result = await resolver.resolve_pmc_full_text(pmc_id)
    print(f"pmc_id={pmc_id}")
    print(f"structured_source={result.source}")
    print(f"structured_url={result.url}")
    print(f"structured_error={result.error}")
    text = result.text or ""
    print(f"structured_text_length={len(text)}")
    if text:
        print("structured_text_preview:")
        print(text[:2000])
    return text


async def _download_pdf(pdf_url: str) -> bytes:
    print(f"download_url={pdf_url}")
    importer = PaperImporter()
    async with httpx.AsyncClient(timeout=settings.pdf_download_timeout_seconds, follow_redirects=True) as client:
        response = await client.get(pdf_url, headers=importer._pdf_download_headers(pdf_url))
        print(f"status_code={response.status_code}")
        print(f"final_url={response.url}")
        print(f"content_type={response.headers.get('content-type')}")
        print(f"content_length={response.headers.get('content-length')}")
        response.raise_for_status()
        data = response.content
        if importer._looks_like_html_response(content=data, content_type=response.headers.get("content-type")):
            print(f"html_preview={data[:500].decode('utf-8', errors='replace').replace(chr(10), ' ')}")
            resolved_url = importer.pdf_resolver.extract_pdf_url_from_html(
                data.decode("utf-8", errors="replace"),
                base_url=str(response.url),
            )
            print(f"html_pdf_link={resolved_url}")
            if not resolved_url:
                pmc_id = importer._pmc_id_from_url(str(response.url)) or importer._pmc_id_from_url(pdf_url)
                print(f"pmc_id_from_url={pmc_id}")
                if pmc_id:
                    resolved = await importer.pdf_resolver.resolve_pmc_pdf(pmc_id)
                    print(f"pmc_resolver_source={resolved.source}")
                    print(f"pmc_resolver_pdf_url={resolved.pdf_url}")
                    print(f"pmc_resolver_error={resolved.error}")
                    resolved_url = resolved.pdf_url
            if importer._should_retry_pdf_url(current_url=str(response.url), resolved_url=resolved_url):
                response = await client.get(resolved_url, headers=importer._pdf_download_headers(resolved_url))
                print(f"retry_status_code={response.status_code}")
                print(f"retry_final_url={response.url}")
                print(f"retry_content_type={response.headers.get('content-type')}")
                print(f"retry_content_length={response.headers.get('content-length')}")
                response.raise_for_status()
                data = response.content
    print(f"downloaded_bytes={len(data)}")
    starts_with_pdf = data.lstrip().startswith(b"%PDF-")
    print(f"starts_with_pdf={starts_with_pdf}")
    if not starts_with_pdf:
        preview = data[:500].decode("utf-8", errors="replace").replace("\n", " ")
        raise SystemExit(f"Downloaded content is not a PDF. preview={preview}")
    return data


def _inspect_pdf(pdf_bytes: bytes, filename: str, output_dir: Path) -> list[bytes]:
    _print_step("render pdf pages")
    output_dir.mkdir(parents=True, exist_ok=True)
    images: list[bytes] = []
    matrix = fitz.Matrix(settings.pdf_render_zoom, settings.pdf_render_zoom)
    with fitz.open(stream=pdf_bytes, filetype="pdf") as document:
        print(f"page_count={document.page_count}")
        native_text = "\n".join(page.get_text("text") for page in document).strip()
        print(f"native_text_length={len(native_text)}")
        print(f"native_text_preview={native_text[:500]}")
        page_count = min(settings.pdf_multimodal_max_pages, document.page_count)
        for page_index in range(page_count):
            page = document.load_page(page_index)
            pixmap = page.get_pixmap(matrix=matrix, alpha=False)
            image_bytes = pixmap.tobytes("png")
            images.append(image_bytes)
            output_path = output_dir / f"{Path(filename).stem}_page_{page_index + 1}.png"
            output_path.write_bytes(image_bytes)
            width = height = "unknown"
            try:
                from PIL import Image

                with Image.open(BytesIO(image_bytes)) as image:
                    width, height = image.size
            except Exception as exc:
                print(f"pil_check_error={exc}")
            print(
                f"page={page_index + 1} png={output_path} bytes={len(image_bytes)} "
                f"size={width}x{height}"
            )
    return images


async def _test_multimodal(images: list[bytes], filename: str) -> str:
    _print_step("multimodal base64 test")
    if not images:
        raise SystemExit("No rendered images to test")
    client = LLMClient()
    try:
        text = await client.extract_text_from_images(images=images, filename=filename)
    except Exception as exc:
        print(f"multimodal_error={type(exc).__name__}: {exc}")
        raise
    print(f"multimodal_text_length={len(text)}")
    print("multimodal_text_preview:")
    print(text[:2000])
    return text


def _test_chunking(text: str) -> list[str]:
    _print_step("chunk test")
    importer = PaperImporter()
    unusable = importer._is_unusable_extracted_text(text)
    chunks = importer._chunk_text(text)
    print(f"is_unusable_text={unusable}")
    print(f"chunk_count={len(chunks)}")
    if chunks:
        print(f"first_chunk_length={len(chunks[0])}")
        print("first_chunk_preview:")
        print(chunks[0][:1000])
    return chunks


async def _test_embedding(chunks: list[str]) -> None:
    _print_step("embedding test")
    if not chunks:
        print("skip_embedding=no_chunks")
        return
    vector = await EmbeddingService().embed_text(chunks[0])
    print(f"embedding_dim={len(vector)}")
    print(f"embedding_first_values={vector[:5]}")


async def main() -> None:
    parser = argparse.ArgumentParser(description="Debug PDF full-text ingestion without writing database or Milvus.")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--paper-id", help="Existing papers.id, used to read pdf_url from PostgreSQL.")
    source.add_argument("--pdf-url", help="Direct PDF URL to download and test.")
    source.add_argument("--file", help="Local PDF file path to test.")
    source.add_argument("--pmc-id", help="PMCID used to test PMC BioC/OAI-PMH structured full text.")
    parser.add_argument(
        "--output-dir",
        default=str(PROJECT_ROOT / "debug_outputs" / "pdf_ingestion_pipeline"),
        help="Directory for rendered PNG pages.",
    )
    parser.add_argument("--skip-llm", action="store_true", help="Only test download/rendering, do not call LLM.")
    parser.add_argument("--skip-embedding", action="store_true", help="Do not call embedding service.")
    args = parser.parse_args()

    _print_config()
    if args.pmc_id:
        text = await _test_pmc_structured_full_text(args.pmc_id)
        chunks = _test_chunking(text)
        if not args.skip_embedding:
            await _test_embedding(chunks)
        return

    structured_text = await _try_structured_full_text_from_source(args)
    if structured_text:
        chunks = _test_chunking(structured_text)
        if not args.skip_embedding:
            await _test_embedding(chunks)
        return

    pdf_bytes, filename = await _load_pdf_bytes(args)
    images = _inspect_pdf(pdf_bytes=pdf_bytes, filename=filename, output_dir=Path(args.output_dir))
    if args.skip_llm:
        return
    text = await _test_multimodal(images=images, filename=filename)
    chunks = _test_chunking(text)
    if not args.skip_embedding:
        await _test_embedding(chunks)


if __name__ == "__main__":
    asyncio.run(main())
