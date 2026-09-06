from __future__ import annotations

import html
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from html.parser import HTMLParser
from typing import Any
from urllib.parse import quote, urljoin

import httpx

from app.config import settings

PMC_OA_SERVICE_URL = "https://www.ncbi.nlm.nih.gov/pmc/utils/oa/oa.fcgi"
EUROPE_PMC_RENDER_URL = "https://europepmc.org/backend/ptpmcrender.fcgi"
PMC_BIOC_JSON_URL = "https://www.ncbi.nlm.nih.gov/research/bionlp/RESTful/pmcoa.cgi/BioC_json/{pmc_id}/unicode"
PMC_OAI_PMH_URL = "https://pmc.ncbi.nlm.nih.gov/api/oai/v1/mh/"


@dataclass
class PDFResolveResult:
    pdf_url: str | None
    landing_url: str | None = None
    source: str = ""
    error: str | None = None


@dataclass
class StructuredFullTextResult:
    text: str | None
    source: str = ""
    url: str | None = None
    error: str | None = None


class _PDFLinkParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.meta_pdf_urls: list[str] = []
        self.anchor_urls: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr_map = {key.lower(): value or "" for key, value in attrs}
        if tag.lower() == "meta":
            name = (attr_map.get("name") or attr_map.get("property") or "").lower()
            content = html.unescape(attr_map.get("content") or "").strip()
            if content and name in {"citation_pdf_url", "dc.identifier", "eprints.document_url"}:
                self.meta_pdf_urls.append(content)
        if tag.lower() == "a":
            href = html.unescape(attr_map.get("href") or "").strip()
            link_type = (attr_map.get("type") or "").lower()
            if href and ("pdf" in href.lower() or "application/pdf" in link_type):
                self.anchor_urls.append(href)


class PDFResolver:
    async def resolve_pmc_full_text(self, pmc_id: str) -> StructuredFullTextResult:
        normalized_pmc_id = self._normalize_pmc_id(pmc_id)
        errors: list[str] = []

        bioc_url = PMC_BIOC_JSON_URL.format(pmc_id=normalized_pmc_id)
        bioc_text, bioc_error = await self._fetch_bioc_text(bioc_url)
        if bioc_text and self._is_usable_full_text(bioc_text):
            return StructuredFullTextResult(text=bioc_text, source="pmc_bioc", url=bioc_url)
        errors.append(f"BioC unavailable: {bioc_error or 'empty or too short'}")

        oai_url = self._oai_pmh_full_text_url(normalized_pmc_id)
        oai_text, oai_error = await self._fetch_oai_pmh_text(oai_url)
        if oai_text and self._is_usable_full_text(oai_text):
            return StructuredFullTextResult(text=oai_text, source="pmc_oai_pmh", url=oai_url)
        errors.append(f"OAI-PMH unavailable: {oai_error or 'empty or too short'}")

        return StructuredFullTextResult(text=None, source="pmc_structured", error="; ".join(errors))

    async def resolve_pubmed_pdf(self, *, doi: str | None, pmc_id: str | None, pmid: str | None) -> PDFResolveResult:
        if pmc_id:
            result = await self.resolve_pmc_pdf(self._normalize_pmc_id(pmc_id))
            if result.pdf_url:
                return result

        if doi:
            return await self.resolve_doi_pdf(doi)

        return PDFResolveResult(pdf_url=None, source="pubmed", error=f"No DOI or PMCID found for PMID {pmid or ''}".strip())

    async def resolve_doi_pdf(self, doi: str) -> PDFResolveResult:
        doi = doi.strip()
        if not doi:
            return PDFResolveResult(pdf_url=None, source="doi", error="DOI is empty")

        landing_url = f"https://doi.org/{quote(doi, safe='/:')}"
        try:
            async with httpx.AsyncClient(
                timeout=settings.external_api_timeout_seconds,
                follow_redirects=True,
                headers=self._browser_headers(),
            ) as client:
                response = await client.get(landing_url)
                response.raise_for_status()
        except httpx.HTTPError as exc:
            return PDFResolveResult(pdf_url=None, landing_url=landing_url, source="doi", error=str(exc))

        final_url = str(response.url)
        content_type = response.headers.get("content-type", "").lower()
        if "application/pdf" in content_type or final_url.lower().split("?", 1)[0].endswith(".pdf"):
            return PDFResolveResult(pdf_url=final_url, landing_url=final_url, source="doi_direct")

        pdf_url = self.extract_pdf_url_from_html(response.text, base_url=final_url)
        if pdf_url:
            return PDFResolveResult(pdf_url=pdf_url, landing_url=final_url, source="doi_landing")

        return PDFResolveResult(
            pdf_url=None,
            landing_url=final_url,
            source="doi_landing",
            error="No PDF link found on DOI landing page",
        )

    async def resolve_pmc_pdf(self, pmc_id: str) -> PDFResolveResult:
        normalized_pmc_id = self._normalize_pmc_id(pmc_id)
        landing_url = f"https://pmc.ncbi.nlm.nih.gov/articles/{normalized_pmc_id}/"
        errors: list[str] = []

        europe_url = f"{EUROPE_PMC_RENDER_URL}?accid={normalized_pmc_id}&blobtype=pdf"
        europe_final_url = await self._verified_pdf_url(europe_url)
        if europe_final_url:
            return PDFResolveResult(pdf_url=europe_final_url, landing_url=landing_url, source="europe_pmc")
        errors.append("Europe PMC PDF endpoint did not return a PDF")

        oa_pdf_url = await self._resolve_pmc_oa_pdf_url(normalized_pmc_id)
        if oa_pdf_url:
            oa_final_url = await self._verified_pdf_url(oa_pdf_url)
            if oa_final_url:
                return PDFResolveResult(pdf_url=oa_final_url, landing_url=landing_url, source="pmc_oa")
            errors.append(f"PMC OA PDF link did not return a PDF: {oa_pdf_url}")
        else:
            errors.append("PMC OA service did not expose a PDF link")

        fallback_url = f"{landing_url}pdf/"
        return PDFResolveResult(
            pdf_url=fallback_url,
            landing_url=landing_url,
            source="pmc_fallback",
            error="; ".join(errors),
        )

    async def _resolve_pmc_oa_pdf_url(self, pmc_id: str) -> str | None:
        params = {"id": pmc_id, "tool": settings.app_name}
        if settings.pubmed_email:
            params["email"] = settings.pubmed_email
        if settings.pubmed_api_key:
            params["api_key"] = settings.pubmed_api_key

        try:
            async with httpx.AsyncClient(
                timeout=settings.external_api_timeout_seconds,
                follow_redirects=True,
                headers=self._browser_headers(accept="application/xml,text/xml,*/*"),
            ) as client:
                response = await client.get(PMC_OA_SERVICE_URL, params=params)
                response.raise_for_status()
        except httpx.HTTPError:
            return None

        try:
            root = ET.fromstring(response.text)
        except ET.ParseError:
            return None

        for link in root.findall(".//link"):
            if (link.attrib.get("format") or "").lower() != "pdf":
                continue
            href = (link.attrib.get("href") or "").strip()
            if href:
                return self._normalize_pmc_oa_href(href)
        return None

    async def _verified_pdf_url(self, url: str) -> str | None:
        try:
            async with httpx.AsyncClient(
                timeout=settings.pdf_download_timeout_seconds,
                follow_redirects=True,
                headers={**self._browser_headers(accept="application/pdf,*/*;q=0.8"), "Range": "bytes=0-4095"},
            ) as client:
                response = await client.get(url)
                response.raise_for_status()
        except httpx.HTTPError:
            return None

        content_type = response.headers.get("content-type", "").lower()
        if "application/pdf" in content_type or response.content.lstrip().startswith(b"%PDF-"):
            return str(response.url)
        return None

    def extract_pdf_url_from_html(self, html_text: str, base_url: str) -> str | None:
        parser = _PDFLinkParser()
        parser.feed(html_text)

        candidates = [*parser.meta_pdf_urls, *parser.anchor_urls]
        for candidate in candidates:
            url = urljoin(base_url, candidate.strip())
            if self._looks_like_pdf_url(url):
                return url
        return None

    def _looks_like_pdf_url(self, url: str) -> bool:
        lowered = url.lower()
        return bool(
            lowered.split("?", 1)[0].endswith(".pdf")
            or re.search(r"[/=&?](pdf|fulltextpdf|download)[/=&?]?", lowered)
            or "citation_pdf_url" in lowered
        )

    def _normalize_pmc_id(self, pmc_id: str) -> str:
        cleaned = pmc_id.strip()
        return cleaned if cleaned.upper().startswith("PMC") else f"PMC{cleaned}"

    def _normalize_pmc_oa_href(self, href: str) -> str:
        if href.startswith("ftp://ftp.ncbi.nlm.nih.gov/"):
            return href.replace("ftp://ftp.ncbi.nlm.nih.gov/", "https://ftp.ncbi.nlm.nih.gov/", 1)
        return href

    async def _fetch_bioc_text(self, url: str) -> tuple[str | None, str | None]:
        try:
            async with httpx.AsyncClient(
                timeout=settings.external_api_timeout_seconds,
                follow_redirects=True,
                headers=self._browser_headers(accept="application/json,*/*;q=0.8"),
            ) as client:
                response = await client.get(url)
                response.raise_for_status()
                payload = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            return None, str(exc)
        return self._extract_bioc_text(payload), None

    async def _fetch_oai_pmh_text(self, url: str) -> tuple[str | None, str | None]:
        try:
            async with httpx.AsyncClient(
                timeout=settings.external_api_timeout_seconds,
                follow_redirects=True,
                headers=self._browser_headers(accept="application/xml,text/xml,*/*;q=0.8"),
            ) as client:
                response = await client.get(url)
                response.raise_for_status()
        except httpx.HTTPError as exc:
            return None, str(exc)

        try:
            root = ET.fromstring(response.text)
        except ET.ParseError as exc:
            return None, str(exc)

        error = self._first_local_text(root, {"error"})
        if error:
            return None, error
        return self._extract_jats_text(root), None

    def _extract_bioc_text(self, payload: dict[str, Any]) -> str:
        parts: list[str] = []
        documents = payload.get("documents") or []
        for document in documents:
            for passage in document.get("passages") or []:
                if not isinstance(passage, dict):
                    continue
                text = self._clean_text(str(passage.get("text") or ""))
                if not text:
                    continue
                infons = passage.get("infons") if isinstance(passage.get("infons"), dict) else {}
                label = (
                    infons.get("section_type")
                    or infons.get("type")
                    or infons.get("section")
                    or infons.get("article_section")
                    or ""
                )
                parts.append(f"[{label}]\n{text}" if label else text)
        return "\n\n".join(parts)

    def _extract_jats_text(self, root: ET.Element) -> str:
        parts: list[str] = []
        for element in root.iter():
            name = self._local_name(element.tag)
            if name == "article-title":
                text = self._element_text(element)
                if text:
                    parts.append(f"[title]\n{text}")
            elif name == "abstract":
                text = self._element_text(element)
                if text:
                    parts.append(f"[abstract]\n{text}")
            elif name == "body":
                body_parts = self._extract_jats_body_parts(element)
                if body_parts:
                    parts.append("[body]\n" + "\n\n".join(body_parts))
                break
        return "\n\n".join(dict.fromkeys(parts))

    def _extract_jats_body_parts(self, body: ET.Element) -> list[str]:
        parts: list[str] = []
        for element in body.iter():
            name = self._local_name(element.tag)
            if name not in {"title", "p", "caption"}:
                continue
            text = self._element_text(element)
            if text:
                parts.append(text)
        return list(dict.fromkeys(parts))

    def _oai_pmh_full_text_url(self, pmc_id: str) -> str:
        numeric_pmc_id = re.sub(r"^PMC", "", pmc_id, flags=re.IGNORECASE)
        identifier = f"oai:pubmedcentral.nih.gov:{numeric_pmc_id}"
        return (
            f"{PMC_OAI_PMH_URL}?verb=GetRecord"
            f"&identifier={quote(identifier, safe=':')}"
            "&metadataPrefix=pmc"
        )

    def _first_local_text(self, root: ET.Element, names: set[str]) -> str:
        for element in root.iter():
            if self._local_name(element.tag) in names:
                return self._element_text(element)
        return ""

    def _local_name(self, tag: str) -> str:
        return tag.rsplit("}", 1)[-1] if "}" in tag else tag

    def _element_text(self, element: ET.Element) -> str:
        return self._clean_text(" ".join(part.strip() for part in element.itertext() if part.strip()))

    def _clean_text(self, text: str) -> str:
        return re.sub(r"\s+", " ", text).strip()

    def _is_usable_full_text(self, text: str | None) -> bool:
        value = str(text or "").strip()
        if not value:
            return False
        meaningful = "".join(ch for ch in value if ch.isalnum() or "\u4e00" <= ch <= "\u9fff")
        return len(meaningful) >= 800

    def _browser_headers(self, accept: str | None = None) -> dict[str, str]:
        return {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0 Safari/537.36"
            ),
            "Accept": accept or "text/html,application/xhtml+xml,application/xml;q=0.9,application/pdf;q=0.8,*/*;q=0.7",
            "Accept-Language": "en-US,en;q=0.9,zh-CN;q=0.8,zh;q=0.7",
            "Cache-Control": "no-cache",
            "Pragma": "no-cache",
        }
