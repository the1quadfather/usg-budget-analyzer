"""
parsing/policy_parser.py

Parses NDAA, NDS, and NSS policy documents into structured chunks
suitable for semantic embedding and cross-reference with R-1 budget data.

Chunking strategy by document type:
  NDAA  — section-based: each numbered SEC. becomes one chunk.
           The NDAA has ~1000 sections; we skip boilerplate (authorization
           amounts, administrative) and keep programmatic/policy sections.
  NDS   — paragraph-group: 3-5 paragraphs per chunk with section header context.
  NSS   — paragraph-group: same as NDS.

Output per chunk:
  - document metadata (type, year, fiscal_year)
  - section_id and section_title where identifiable
  - cleaned text (no headers/footers/page numbers)
  - approximate token count

Usage:
    parser = PolicyParser()

    # Parse all downloaded documents into DB
    parser.parse_all()

    # Parse a single file
    parser.parse_file(Path("data/raw/policy/ndaa/ndaa_fy2024.pdf"),
                      doc_type="NDAA", year=2024, fiscal_year=2024)

CLI:
    python parsing/policy_parser.py --all
    python parsing/policy_parser.py --type NDAA --years 2022 2023 2024 2025
    python parsing/policy_parser.py --type NDS
"""

import logging
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import pdfplumber
from sqlalchemy.orm import Session

sys.path.insert(0, str(Path(__file__).parent.parent))
import config
from storage.db import PolicyChunk, PolicyDocument, get_engine, get_session_factory, init_db

logger = logging.getLogger(__name__)

# ── Document directories ──────────────────────────────────────────────────────

NDAA_DIR = config.RAW_DIR / "policy" / "ndaa"
NDS_DIR  = config.RAW_DIR / "policy" / "nds"
NSS_DIR  = config.RAW_DIR / "policy" / "nss"

# ── Chunk config ──────────────────────────────────────────────────────────────

# Approximate token counts (1 token ≈ 4 chars)
NDAA_MIN_SECTION_TOKENS = 50    # skip very short sections (boilerplate)
NDAA_MAX_SECTION_TOKENS = 800   # split oversized sections
NDS_CHUNK_PARAGRAPHS    = 4     # paragraphs per NDS/NSS chunk
NDS_OVERLAP_PARAGRAPHS  = 1     # paragraph overlap between chunks


# ── Chunk dataclass ───────────────────────────────────────────────────────────

@dataclass
class ParsedChunk:
    chunk_index: int
    page_number: int | None
    section_id: str | None       # "SEC. 215" or "SECTION 2.1" etc.
    section_title: str | None    # title text after the section ID
    text: str
    token_count: int


# ── Text extraction ───────────────────────────────────────────────────────────

def _extract_pages(pdf_path: Path) -> list[str]:
    """Extract pages as text using pdftotext -layout, fall back to pdfplumber."""
    try:
        result = subprocess.run(
            ["pdftotext", "-layout", str(pdf_path), "-"],
            capture_output=True, text=True, check=True,
            encoding="utf-8", errors="replace",
        )
        return result.stdout.split("\f")
    except (FileNotFoundError, subprocess.CalledProcessError):
        logger.warning(f"pdftotext unavailable for {pdf_path.name}, using pdfplumber")
        with pdfplumber.open(pdf_path) as pdf:
            return [p.extract_text(layout=True) or "" for p in pdf.pages]


def _clean_text(text: str) -> str:
    """Remove headers, footers, page numbers, and excessive whitespace."""
    lines = text.split("\n")
    cleaned = []
    for line in lines:
        stripped = line.strip()
        # Skip empty lines
        if not stripped:
            cleaned.append("")
            continue
        # Skip page number lines (standalone numbers)
        if re.match(r"^\d+$", stripped):
            continue
        # Skip common header/footer patterns
        if re.match(
            r"^(UNCLASSIFIED|PUBLIC LAW|ENROLLED BILL|"
            r"GPO|U\.S\. GOVERNMENT|www\.|https?://)",
            stripped, re.IGNORECASE
        ):
            continue
        cleaned.append(stripped)

    # Collapse multiple blank lines into one
    result = re.sub(r"\n{3,}", "\n\n", "\n".join(cleaned))
    return result.strip()


def _approx_tokens(text: str) -> int:
    """Approximate token count (1 token ≈ 4 characters)."""
    return max(1, len(text) // 4)


# ── NDAA Parser ───────────────────────────────────────────────────────────────

# Matches: "SEC. 215.", "SECTION 215.", "Sec. 1501.", "SEC. 1501A."
NDAA_SECTION_RE = re.compile(
    r"^(?:SEC(?:TION)?\.?\s+)(\d+[A-Z]?)\.\s*(.{0,200}?)(?:\.|$)",
    re.IGNORECASE | re.MULTILINE,
)

# NDAA sections we skip — pure authorization amounts and admin boilerplate
NDAA_SKIP_PATTERNS = re.compile(
    r"^(?:short title|table of contents|definitions|authorization of appropriations"
    r"|amounts authorized|findings|sense of congress"
    r"|effective date|severability|repeals?|amendments? to title)",
    re.IGNORECASE,
)

# NDAA sections we prioritize — programmatic/policy content
NDAA_PRIORITY_KEYWORDS = re.compile(
    r"\b(program|system|capability|technology|development|research|"
    r"weapon|missile|aircraft|ship|cyber|space|intelligence|"
    r"hypersonic|unmanned|autonomous|artificial intelligence|"
    r"directed energy|electronic warfare|C2|command and control|"
    r"modernization|acquisition|prototype|demonstration)\b",
    re.IGNORECASE,
)


class NDAAPParser:
    """Parses NDAA PDFs into section-level chunks."""

    def parse(self, pdf_path: Path) -> list[ParsedChunk]:
        pages = _extract_pages(pdf_path)
        full_text = "\n".join(pages)
        full_text = _clean_text(full_text)

        # Find all section boundaries
        section_spans: list[tuple[int, str, str]] = []
        for m in NDAA_SECTION_RE.finditer(full_text):
            sec_id   = f"SEC. {m.group(1)}"
            sec_title = m.group(2).strip().rstrip(".")
            section_spans.append((m.start(), sec_id, sec_title))

        if not section_spans:
            # Fallback: treat whole document as one chunk per 500 tokens
            return self._chunk_flat(full_text, pages)

        chunks: list[ParsedChunk] = []
        for i, (start, sec_id, sec_title) in enumerate(section_spans):
            end = section_spans[i + 1][0] if i + 1 < len(section_spans) else len(full_text)
            section_text = full_text[start:end].strip()

            # Skip boilerplate sections
            if NDAA_SKIP_PATTERNS.search(sec_title):
                continue

            # Skip very short sections
            if _approx_tokens(section_text) < NDAA_MIN_SECTION_TOKENS:
                continue

            # Split oversized sections into sub-chunks
            if _approx_tokens(section_text) > NDAA_MAX_SECTION_TOKENS:
                sub_chunks = self._split_section(section_text, sec_id, sec_title)
                chunks.extend(sub_chunks)
            else:
                # Estimate page number
                page_num = self._estimate_page(start, full_text, pages)
                chunks.append(ParsedChunk(
                    chunk_index=len(chunks),
                    page_number=page_num,
                    section_id=sec_id,
                    section_title=sec_title[:500] if sec_title else None,
                    text=section_text,
                    token_count=_approx_tokens(section_text),
                ))

        # Re-index
        for i, c in enumerate(chunks):
            c.chunk_index = i

        logger.info(f"  NDAA parser: {len(chunks)} section chunks")
        return chunks

    def _split_section(
        self, text: str, sec_id: str, sec_title: str
    ) -> list[ParsedChunk]:
        """Split an oversized section into paragraph-grouped sub-chunks."""
        paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
        sub_chunks = []
        current_paras: list[str] = []
        current_tokens = 0

        for para in paragraphs:
            tokens = _approx_tokens(para)
            if current_tokens + tokens > NDAA_MAX_SECTION_TOKENS and current_paras:
                sub_chunks.append(ParsedChunk(
                    chunk_index=0,
                    page_number=None,
                    section_id=sec_id,
                    section_title=sec_title[:500] if sec_title else None,
                    text="\n\n".join(current_paras),
                    token_count=current_tokens,
                ))
                current_paras = [para]
                current_tokens = tokens
            else:
                current_paras.append(para)
                current_tokens += tokens

        if current_paras:
            sub_chunks.append(ParsedChunk(
                chunk_index=0,
                page_number=None,
                section_id=sec_id,
                section_title=sec_title[:500] if sec_title else None,
                text="\n\n".join(current_paras),
                token_count=current_tokens,
            ))
        return sub_chunks

    @staticmethod
    def _chunk_flat(full_text: str, pages: list[str]) -> list[ParsedChunk]:
        """Fallback: split by paragraphs when no section markers found."""
        paragraphs = [p.strip() for p in full_text.split("\n\n") if p.strip()]
        chunks = []
        window: list[str] = []
        tokens = 0
        for para in paragraphs:
            t = _approx_tokens(para)
            if tokens + t > 500 and window:
                chunks.append(ParsedChunk(
                    chunk_index=len(chunks),
                    page_number=None,
                    section_id=None,
                    section_title=None,
                    text="\n\n".join(window),
                    token_count=tokens,
                ))
                window = [para]
                tokens = t
            else:
                window.append(para)
                tokens += t
        if window:
            chunks.append(ParsedChunk(
                chunk_index=len(chunks),
                page_number=None,
                section_id=None,
                section_title=None,
                text="\n\n".join(window),
                token_count=tokens,
            ))
        return chunks

    @staticmethod
    def _estimate_page(char_pos: int, full_text: str, pages: list[str]) -> int | None:
        """Estimate page number from character position in full text."""
        try:
            cumulative = 0
            for i, page in enumerate(pages):
                cumulative += len(page)
                if cumulative >= char_pos:
                    return i + 1
        except Exception:
            pass
        return None


# ── NDS / NSS Parser ─────────────────────────────────────────────────────────

# Matches section/chapter headings in NDS/NSS documents
NDS_SECTION_RE = re.compile(
    r"^([A-Z][A-Z\s\&\-]{3,60}|[IVX]+\.\s+[A-Z][A-Z\s]{3,})\s*$",
    re.MULTILINE,
)


class NDSParser:
    """
    Parses NDS and NSS PDFs into paragraph-grouped chunks with
    section header context preserved.
    """

    def parse(self, pdf_path: Path) -> list[ParsedChunk]:
        pages = _extract_pages(pdf_path)
        chunks: list[ParsedChunk] = []
        current_section = "Introduction"

        for page_num, page_text in enumerate(pages, 1):
            clean = _clean_text(page_text)
            if not clean:
                continue

            # Update current section from any headers on this page
            for m in NDS_SECTION_RE.finditer(clean):
                heading = m.group(1).strip()
                if len(heading) > 5 and not heading.isdigit():
                    current_section = heading

            # Split page into paragraphs and group them
            paragraphs = [p.strip() for p in clean.split("\n\n") if p.strip()]
            if not paragraphs:
                continue

            # Slide a window of NDS_CHUNK_PARAGRAPHS paragraphs
            step = max(1, NDS_CHUNK_PARAGRAPHS - NDS_OVERLAP_PARAGRAPHS)
            for i in range(0, len(paragraphs), step):
                window = paragraphs[i: i + NDS_CHUNK_PARAGRAPHS]
                if not window:
                    continue
                text = "\n\n".join(window)
                tokens = _approx_tokens(text)
                if tokens < 30:  # skip very short fragments
                    continue
                chunks.append(ParsedChunk(
                    chunk_index=len(chunks),
                    page_number=page_num,
                    section_id=None,
                    section_title=current_section[:500],
                    text=text,
                    token_count=tokens,
                ))

        logger.info(f"  NDS/NSS parser: {len(chunks)} paragraph chunks")
        return chunks


# ── Main Parser ───────────────────────────────────────────────────────────────

class PolicyParser:
    """
    Orchestrates parsing of all policy documents and ingestion into SQLite.

    Example:
        engine = get_engine("sqlite:///data/processed/usg_budgets.db")
        init_db(engine)
        SessionFactory = get_session_factory(engine)
        with SessionFactory() as session:
            parser = PolicyParser(session)
            parser.parse_all()
    """

    DOC_CONFIGS = [
        # (directory, doc_type, year_from_filename_pattern)
        (NDAA_DIR, "NDAA"),
        (NDS_DIR,  "NDS"),
        (NSS_DIR,  "NSS"),
    ]

    def __init__(self, session: Session):
        self.session = session
        self.ndaa_parser = NDAAPParser()
        self.nds_parser  = NDSParser()

    def parse_all(
        self,
        doc_types: list[str] | None = None,
        years: list[int] | None = None,
        replace_existing: bool = False,
    ) -> dict[str, int]:
        """
        Parse all documents found in the policy directories.

        Args:
            doc_types:        filter to ["NDAA", "NDS", "NSS"] subset
            years:            filter to specific years
            replace_existing: if True, re-parse documents already in DB

        Returns:
            {filename: chunk_count}
        """
        results: dict[str, int] = {}
        for directory, doc_type in self.DOC_CONFIGS:
            if doc_types and doc_type not in doc_types:
                continue
            if not directory.exists():
                continue
            for pdf_path in sorted(directory.glob("*.pdf")):
                year = self._infer_year(pdf_path.name)
                if years and year not in years:
                    continue
                fiscal_year = year if doc_type == "NDAA" else None
                n = self.parse_file(
                    pdf_path, doc_type, year, fiscal_year,
                    replace_existing=replace_existing,
                )
                results[pdf_path.name] = n

        total = sum(results.values())
        logger.info(
            f"parse_all complete: {len(results)} documents, "
            f"{total} total chunks"
        )
        return results

    def parse_file(
        self,
        pdf_path: Path,
        doc_type: str,
        year: int,
        fiscal_year: int | None = None,
        replace_existing: bool = False,
    ) -> int:
        """
        Parse a single policy PDF and store chunks in DB.
        Returns number of chunks created (0 if skipped).
        """
        pdf_path = Path(pdf_path)
        if not pdf_path.exists():
            logger.warning(f"File not found: {pdf_path}")
            return 0

        # Check if already processed
        existing = self.session.query(PolicyDocument).filter_by(
            filename=pdf_path.name
        ).first()

        if existing and not replace_existing:
            logger.info(f"  Already in DB, skipping: {pdf_path.name}")
            return 0

        if existing and replace_existing:
            self.session.delete(existing)
            self.session.flush()

        # Count pages
        try:
            with pdfplumber.open(pdf_path) as pdf:
                page_count = len(pdf.pages)
        except Exception:
            page_count = None

        logger.info(
            f"Parsing {pdf_path.name} "
            f"({doc_type} {year}, {page_count or '?'} pages) ..."
        )

        # Route to correct parser
        if doc_type == "NDAA":
            raw_chunks = self.ndaa_parser.parse(pdf_path)
        else:
            raw_chunks = self.nds_parser.parse(pdf_path)

        if not raw_chunks:
            logger.warning(f"  No chunks extracted from {pdf_path.name}")
            return 0

        # Save to DB
        doc = PolicyDocument(
            filename=pdf_path.name,
            doc_type=doc_type,
            year=year,
            fiscal_year=fiscal_year,
            page_count=page_count,
        )
        self.session.add(doc)
        self.session.flush()

        chunk_objects = [
            PolicyChunk(
                document_id=doc.id,
                chunk_index=c.chunk_index,
                page_number=c.page_number,
                section_id=c.section_id,
                section_title=c.section_title,
                text=c.text,
                token_count=c.token_count,
            )
            for c in raw_chunks
        ]
        self.session.bulk_save_objects(chunk_objects)
        self.session.commit()

        logger.info(
            f"  → {len(raw_chunks)} chunks stored for {pdf_path.name}"
        )
        return len(raw_chunks)

    def print_summary(self) -> None:
        """Print a summary of what's been parsed into the DB."""
        from sqlalchemy import func
        rows = (
            self.session.query(
                PolicyDocument.doc_type,
                PolicyDocument.year,
                PolicyDocument.filename,
                func.count(PolicyChunk.id).label("chunks"),
            )
            .outerjoin(PolicyChunk)
            .group_by(PolicyDocument.id)
            .order_by(PolicyDocument.doc_type, PolicyDocument.year)
            .all()
        )
        print(f"\n{'='*65}")
        print("Policy Documents in DB")
        print(f"{'='*65}")
        print(f"{'Type':<8} {'Year':<6} {'Chunks':>7}  {'File'}")
        print(f"{'-'*65}")
        for doc_type, year, filename, chunks in rows:
            print(f"{doc_type:<8} {year:<6} {chunks:>7}  {filename}")
        print(f"{'='*65}")
        total_chunks = sum(r[3] for r in rows)
        print(f"Total: {len(rows)} documents, {total_chunks:,} chunks")

    @staticmethod
    def _infer_year(filename: str) -> int:
        """Infer year from filename e.g. ndaa_fy2024.pdf -> 2024, nds_2022.pdf -> 2022."""
        m = re.search(r"(\d{4})", filename)
        return int(m.group(1)) if m else 0


# ── CLI ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    _HERE = Path(__file__).parent.parent
    DEFAULT_DB = f"sqlite:///{_HERE}/data/processed/usg_budgets.db"

    cli = argparse.ArgumentParser(description="Parse policy documents into DB")
    cli.add_argument("--all",   action="store_true", help="Parse all documents")
    cli.add_argument("--type",  nargs="+", choices=["NDAA", "NDS", "NSS"],
                     help="Document types to parse")
    cli.add_argument("--years", nargs="+", type=int, help="Filter by year")
    cli.add_argument("--replace", action="store_true",
                     help="Re-parse documents already in DB")
    cli.add_argument("--summary", action="store_true",
                     help="Print DB summary and exit")
    cli.add_argument("--db", default=DEFAULT_DB)
    args = cli.parse_args()

    engine = get_engine(args.db)
    init_db(engine)
    SessionFactory = get_session_factory(engine)

    with SessionFactory() as session:
        parser = PolicyParser(session)

        if args.summary:
            parser.print_summary()
        elif args.all or args.type:
            results = parser.parse_all(
                doc_types=args.type,
                years=args.years,
                replace_existing=args.replace,
            )
            print(f"\nParsed {len(results)} documents:")
            for fname, n in results.items():
                print(f"  {fname:<45} {n:>5} chunks")
            parser.print_summary()
        else:
            cli.print_help()