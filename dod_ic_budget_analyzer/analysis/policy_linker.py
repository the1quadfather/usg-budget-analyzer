"""
analysis/policy_linker.py

Cross-references policy documents (NDAA, NDS, NSS) with R-1 budget data.

Two analysis modes:

1. CHUNK → PE  (bottom-up)
   For each policy chunk, find the most semantically similar PEs.
   Answers: "Which programs does this NDS priority area fund?"

2. PE → CHUNK  (top-down)
   For a given PE (or search query), find the policy chunks that
   mention it or its domain.
   Answers: "What policy language justifies this program's funding?"

Gap analysis:
   For a given NDS priority area, find PEs that semantically match,
   then show their funding trajectory. Flag if funding decreased in
   years after the policy was published.

Architecture:
   - PolicyChunkEmbedder: encodes all policy chunks once and caches
     embeddings as a numpy .npy file alongside the DB (fast re-use)
   - PolicyLinker: runs similarity searches between chunks and PEs,
     produces analysis DataFrames

Usage:
    engine = get_engine(DB_URI)
    SessionFactory = get_session_factory(engine)

    with SessionFactory() as session:
        linker = PolicyLinker(session)

        # Find PEs related to NDS 2022 priority areas
        df = linker.nds_to_pe_mapping(nds_year=2022, top_n=5)

        # For a specific PE, find relevant policy language
        df = linker.pe_to_policy("0604114A", top_n=10)

        # Gap analysis: hypersonics funding vs NDS mentions
        df = linker.gap_analysis(policy_query="hypersonic", start_fy=2020, end_fy=2026)
"""

import logging
import os
from pathlib import Path
from typing import Optional

import numpy as np
import polars as pl
import torch
from sentence_transformers import SentenceTransformer, util
from sqlalchemy import select, func
from sqlalchemy.orm import Session
from tqdm import tqdm

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))
from storage.db import (
    FundingLine, PolicyChunk, PolicyDocument, ProgramElement
)

logger = logging.getLogger(__name__)

# ── Config ────────────────────────────────────────────────────────────────────

_HERE = Path(__file__).parent.parent
EMBEDDING_CACHE_DIR = _HERE / "data" / "processed" / "embeddings"
EMBEDDING_CACHE_DIR.mkdir(parents=True, exist_ok=True)

DEFAULT_MODEL = "multi-qa-MiniLM-L6-cos-v1"


# ── Embedder ──────────────────────────────────────────────────────────────────

class PolicyChunkEmbedder:
    """
    Encodes all PolicyChunk texts into a dense embedding matrix.
    Caches to disk so re-runs are instant.

    Cache file: data/processed/embeddings/policy_chunks_{model_name}.npy
    """

    def __init__(self, session: Session, model_name: str = DEFAULT_MODEL):
        self.session = session
        self.model_name = model_name

        device = (
            "cuda" if torch.cuda.is_available()
            else "mps" if torch.backends.mps.is_available()
            else "cpu"
        )
        self.model = SentenceTransformer(model_name, device=device)

        self._chunk_ids:    list[int] = []
        self._chunk_texts:  list[str] = []
        self._doc_ids:      list[int] = []
        self._doc_types:    list[str] = []
        self._doc_years:    list[int] = []
        self._doc_fys:      list[int | None] = []
        self._section_ids:  list[str | None] = []
        self._section_titles: list[str | None] = []
        self._embeddings:   Optional[torch.Tensor] = None

        self._load_metadata()
        self._load_or_compute_embeddings()

    # ── Load ──────────────────────────────────────────────────────────────────

    def _load_metadata(self) -> None:
        """Load chunk metadata from DB (fast — no text needed for metadata)."""
        rows = self.session.execute(
            select(
                PolicyChunk.id,
                PolicyChunk.text,
                PolicyChunk.section_id,
                PolicyChunk.section_title,
                PolicyDocument.id.label("doc_id"),
                PolicyDocument.doc_type,
                PolicyDocument.year,
                PolicyDocument.fiscal_year,
            )
            .join(PolicyDocument, PolicyChunk.document_id == PolicyDocument.id)
            .order_by(PolicyDocument.doc_type, PolicyDocument.year, PolicyChunk.chunk_index)
        ).all()

        for r in rows:
            self._chunk_ids.append(r[0])
            self._chunk_texts.append(r[1])
            self._section_ids.append(r[2])
            self._section_titles.append(r[3])
            self._doc_ids.append(r[4])
            self._doc_types.append(r[5])
            self._doc_years.append(r[6])
            self._doc_fys.append(r[7])

        logger.info(f"Loaded {len(self._chunk_ids):,} policy chunk metadata entries")

    def _load_or_compute_embeddings(self) -> None:
        """Load cached embeddings or compute and cache them."""
        safe_model = self.model_name.replace("/", "_").replace("-", "_")
        cache_path = EMBEDDING_CACHE_DIR / f"policy_chunks_{safe_model}.npy"

        if cache_path.exists():
            logger.info(f"Loading cached embeddings from {cache_path.name} ...")
            arr = np.load(str(cache_path))
            if arr.shape[0] == len(self._chunk_ids):
                self._embeddings = torch.tensor(arr)
                logger.info(f"  Loaded {arr.shape[0]:,} embeddings from cache")
                return
            else:
                logger.warning(
                    f"Cache size mismatch ({arr.shape[0]} vs "
                    f"{len(self._chunk_ids)}) — recomputing"
                )

        logger.info(f"Computing embeddings for {len(self._chunk_texts):,} chunks ...")
        self._embeddings = self.model.encode(
            self._chunk_texts,
            convert_to_tensor=True,
            normalize_embeddings=True,
            show_progress_bar=True,
            batch_size=64,
        )
        np.save(str(cache_path), self._embeddings.cpu().numpy())
        logger.info(f"Embeddings cached to {cache_path}")

    # ── Search ────────────────────────────────────────────────────────────────

    def search(
        self,
        query: str,
        top_n: int = 10,
        threshold: float = 0.30,
        doc_type_filter: list[str] | None = None,
        year_filter: list[int] | None = None,
        fy_filter: list[int] | None = None,
    ) -> list[dict]:
        """
        Find the top-N policy chunks most similar to a query string.

        Returns list of dicts with chunk metadata + similarity score.
        """
        if self._embeddings is None or not query.strip():
            return []

        q_emb = self.model.encode(
            query, convert_to_tensor=True, normalize_embeddings=True
        )
        scores = util.cos_sim(q_emb, self._embeddings)[0]
        top_k  = torch.topk(scores, k=min(top_n * 5, len(self._chunk_ids)))

        results = []
        for score_t, idx_t in zip(top_k.values, top_k.indices):
            score = score_t.item()
            idx   = idx_t.item()
            if score < threshold:
                break

            doc_type = self._doc_types[idx]
            year     = self._doc_years[idx]
            fy       = self._doc_fys[idx]

            if doc_type_filter and doc_type not in doc_type_filter:
                continue
            if year_filter and year not in year_filter:
                continue
            if fy_filter and fy not in fy_filter:
                continue

            results.append({
                "chunk_id":      self._chunk_ids[idx],
                "doc_id":        self._doc_ids[idx],
                "doc_type":      doc_type,
                "year":          year,
                "fiscal_year":   fy,
                "section_id":    self._section_ids[idx],
                "section_title": self._section_titles[idx],
                "text":          self._chunk_texts[idx][:400],  # truncate for display
                "score":         round(score, 4),
            })
            if len(results) >= top_n:
                break

        return results

    def invalidate_cache(self) -> None:
        """Delete the embedding cache to force recomputation on next load."""
        safe_model = self.model_name.replace("/", "_").replace("-", "_")
        cache_path = EMBEDDING_CACHE_DIR / f"policy_chunks_{safe_model}.npy"
        if cache_path.exists():
            cache_path.unlink()
            logger.info(f"Embedding cache deleted: {cache_path}")

    @property
    def size(self) -> int:
        return len(self._chunk_ids)


# ── Linker ────────────────────────────────────────────────────────────────────

class PolicyLinker:
    """
    Cross-references policy document chunks with R-1 PE records.

    Example:
        with SessionFactory() as session:
            linker = PolicyLinker(session)

            # Which PEs map to NDS 2022 "integrated deterrence"?
            df = linker.policy_to_pes("integrated deterrence",
                                      doc_type="NDS", year=2022)

            # What policy language covers hypersonics?
            df = linker.query_policy("hypersonic strike",
                                     doc_type_filter=["NDS", "NSS"])

            # Full gap analysis
            df = linker.gap_analysis("hypersonic", start_fy=2020, end_fy=2026)
    """

    def __init__(
        self,
        session: Session,
        model_name: str = DEFAULT_MODEL,
    ):
        self.session = session
        self.embedder = PolicyChunkEmbedder(session, model_name)

        # Load PE corpus for reverse lookups
        self._pe_ids:      list[int] = []
        self._pe_numbers:  list[str] = []
        self._pe_names:    list[str] = []
        self._pe_agencies: list[str] = []
        self._pe_bas:      list[str] = []
        self._pe_embeddings: Optional[torch.Tensor] = None

        self._load_pe_corpus()

    # ── PE corpus ─────────────────────────────────────────────────────────────

    def _load_pe_corpus(self) -> None:
        """Load non-classified PEs and compute/cache their embeddings."""
        rows = self.session.execute(
            select(
                ProgramElement.id,
                ProgramElement.pe_number,
                ProgramElement.program_name,
                ProgramElement.agency,
                ProgramElement.budget_activity,
            ).where(ProgramElement.is_classified == False)  # noqa: E712
        ).all()

        safe_model = self.embedder.model_name.replace("/", "_").replace("-", "_")
        pe_cache = EMBEDDING_CACHE_DIR / f"pe_corpus_{safe_model}.npy"

        texts = []
        for pe_id, pe_num, name, agency, ba in rows:
            self._pe_ids.append(pe_id)
            self._pe_numbers.append(pe_num or "")
            self._pe_names.append(name or "")
            self._pe_agencies.append(agency or "")
            self._pe_bas.append(ba or "")
            texts.append(name or "")

        if pe_cache.exists():
            arr = np.load(str(pe_cache))
            if arr.shape[0] == len(texts):
                self._pe_embeddings = torch.tensor(arr)
                logger.info(f"PE corpus: {len(texts):,} PEs (from cache)")
                return
            else:
                logger.warning("PE cache size mismatch — recomputing")

        logger.info(f"Encoding {len(texts):,} PE titles ...")
        self._pe_embeddings = self.embedder.model.encode(
            texts,
            convert_to_tensor=True,
            normalize_embeddings=True,
            show_progress_bar=len(texts) > 500,
            batch_size=64,
        )
        np.save(str(pe_cache), self._pe_embeddings.cpu().numpy())
        logger.info(f"PE embeddings cached")

    # ── Public analysis methods ───────────────────────────────────────────────

    def query_policy(
        self,
        query: str,
        top_n: int = 10,
        threshold: float = 0.30,
        doc_type_filter: list[str] | None = None,
        year_filter: list[int] | None = None,
    ) -> pl.DataFrame:
        """
        Find policy chunks most relevant to a query.
        Use this to find what policy documents say about a topic.

        Example:
            df = linker.query_policy("hypersonic glide vehicle", doc_type_filter=["NDS"])
        """
        hits = self.embedder.search(
            query, top_n=top_n, threshold=threshold,
            doc_type_filter=doc_type_filter, year_filter=year_filter,
        )
        if not hits:
            return pl.DataFrame()

        return pl.DataFrame(hits, schema={
            "chunk_id":      pl.Int64,
            "doc_type":      pl.Utf8,
            "year":          pl.Int64,
            "fiscal_year":   pl.Int64,
            "section_id":    pl.Utf8,
            "section_title": pl.Utf8,
            "text":          pl.Utf8,
            "score":         pl.Float64,
        })

    def policy_to_pes(
        self,
        query: str,
        doc_type: str | None = None,
        year: int | None = None,
        top_n: int = 10,
        chunk_threshold: float = 0.35,
        pe_threshold: float = 0.35,
    ) -> pl.DataFrame:
        """
        Find PEs related to a policy topic.

        Works in two directions:
          1. Find policy chunks matching the query
          2. For each top chunk, find similar PEs

        Returns a ranked DataFrame of PE + policy context + funding.

        Example:
            df = linker.policy_to_pes("integrated deterrence", doc_type="NDS", year=2022)
        """
        if self._pe_embeddings is None:
            return pl.DataFrame()

        # Direct PE search by query
        q_emb = self.embedder.model.encode(
            query, convert_to_tensor=True, normalize_embeddings=True
        )
        pe_scores = util.cos_sim(q_emb, self._pe_embeddings)[0]
        top_pe = torch.topk(pe_scores, k=min(top_n * 3, len(self._pe_ids)))

        # Also search policy chunks to get context
        doc_type_f = [doc_type] if doc_type else None
        year_f     = [year]     if year     else None
        policy_hits = self.embedder.search(
            query, top_n=5, threshold=chunk_threshold,
            doc_type_filter=doc_type_f, year_filter=year_f,
        )

        # Build policy context string
        policy_context = "; ".join(
            f"[{h['doc_type']} {h['year']} {h['section_title'] or ''}]"
            for h in policy_hits[:3]
        )

        rows = []
        for score_t, idx_t in zip(top_pe.values, top_pe.indices):
            score = score_t.item()
            idx   = idx_t.item()
            if score < pe_threshold:
                break
            if len(rows) >= top_n:
                break

            pe_id = self._pe_ids[idx]
            rows.append({
                "pe_id":           pe_id,
                "pe_number":       self._pe_numbers[idx],
                "program_name":    self._pe_names[idx],
                "agency":          self._pe_agencies[idx],
                "budget_activity": self._pe_bas[idx],
                "relevance_score": round(score, 4),
                "policy_context":  policy_context,
            })

        if not rows:
            return pl.DataFrame()

        df = pl.DataFrame(rows)

        # Attach latest BY Request funding
        pe_ids = df["pe_id"].to_list()
        funding = self._get_latest_funding(pe_ids)
        if funding:
            df_funding = pl.DataFrame(funding, schema={
                "pe_id":   pl.Int64,
                "latest_fy": pl.Int64,
                "latest_by_request_m": pl.Float64,
                "trend": pl.Utf8,
            })
            df = df.join(df_funding, on="pe_id", how="left")

        return df.sort("relevance_score", descending=True)

    def pe_to_policy(
        self,
        pe_identifier: str,
        top_n: int = 10,
        threshold: float = 0.30,
        doc_type_filter: list[str] | None = None,
    ) -> pl.DataFrame:
        """
        Find policy chunks relevant to a specific PE.
        pe_identifier: PE number (e.g. "0604114A") or program name fragment.

        Example:
            df = linker.pe_to_policy("0604114A")  # LTAMDS
            df = linker.pe_to_policy("hypersonics")
        """
        # Resolve PE name to use as query
        query = pe_identifier
        row = self.session.execute(
            select(ProgramElement.program_name)
            .where(ProgramElement.pe_number == pe_identifier)
        ).first()
        if row:
            query = row[0]

        return self.query_policy(
            query, top_n=top_n, threshold=threshold,
            doc_type_filter=doc_type_filter,
        )

    def gap_analysis(
        self,
        policy_query: str,
        start_fy: int,
        end_fy: int,
        doc_type_filter: list[str] | None = None,
        top_n_pes: int = 10,
        min_relevance: float = 0.40,
    ) -> pl.DataFrame:
        """
        Core gap analysis: for a policy priority area, show matched PEs
        and whether their funding trajectory follows stated priorities.

        Returns a wide DataFrame with:
          - PE identity columns
          - BY Request funding for each FY in [start_fy, end_fy]
          - trend direction (up / down / flat)
          - policy relevance score
          - supporting policy document references

        Example:
            df = linker.gap_analysis("hypersonic strike weapons",
                                     start_fy=2020, end_fy=2026,
                                     doc_type_filter=["NDS"])
        """
        # Find relevant PEs
        # Use first doc_type filter value if provided (policy_to_pes takes singular)
        doc_type_single = doc_type_filter[0] if doc_type_filter else None
        df_pes = self.policy_to_pes(
            policy_query,
            doc_type=doc_type_single,
            top_n=top_n_pes,
            pe_threshold=min_relevance,
        )
        if df_pes.is_empty():
            logger.warning(f"No PEs found for query: '{policy_query}'")
            return pl.DataFrame()

        pe_ids = df_pes["pe_id"].to_list()

        # Fetch funding for all matched PEs across the FY range
        funding_rows = self.session.execute(
            select(
                FundingLine.program_element_id,
                FundingLine.fiscal_year,
                FundingLine.amount_thousands,
            )
            .where(
                FundingLine.program_element_id.in_(pe_ids),
                FundingLine.funding_type == "BY Request",
                FundingLine.fiscal_year.between(start_fy, end_fy),
            )
            .order_by(FundingLine.program_element_id, FundingLine.fiscal_year)
        ).all()

        if not funding_rows:
            return df_pes.select([
                "pe_number", "program_name", "agency",
                "budget_activity", "relevance_score", "policy_context",
            ])

        # Pivot funding wide
        df_fund = pl.DataFrame(funding_rows, schema={
            "pe_id":            pl.Int64,
            "fiscal_year":      pl.Int64,
            "amount_thousands": pl.Float64,
        }, orient="row")

        df_wide = df_fund.pivot(
            index="pe_id",
            on="fiscal_year",
            values="amount_thousands",
            aggregate_function="sum",
        ).fill_null(0.0)

        # pe_id becomes float after pivot — cast back to Int64 for join
        df_wide = df_wide.with_columns(pl.col("pe_id").cast(pl.Int64))

        # Rename year columns to fy_{year}
        year_cols = [c for c in df_wide.columns if c.isdigit()]
        rename_map = {c: f"FY{c}_$M" for c in year_cols}
        df_wide = df_wide.rename(rename_map)

        # Convert $K -> $M
        for col in df_wide.columns:
            if col.startswith("FY") and col.endswith("$M"):
                df_wide = df_wide.with_columns(
                    (pl.col(col) / 1_000).alias(col)
                )

        # Compute trend direction
        fy_cols_sorted = sorted(
            [c for c in df_wide.columns if c.startswith("FY")],
            key=lambda x: int(x[2:6])
        )
        if len(fy_cols_sorted) >= 2:
            first_col = fy_cols_sorted[0]
            last_col  = fy_cols_sorted[-1]
            df_wide = df_wide.with_columns(
                pl.when(pl.col(last_col) > pl.col(first_col) * 1.05)
                  .then(pl.lit("↑ UP"))
                  .when(pl.col(last_col) < pl.col(first_col) * 0.95)
                  .then(pl.lit("↓ DOWN"))
                  .otherwise(pl.lit("→ FLAT"))
                  .alias("funding_trend")
            )

        # Join with PE metadata
        df_result = df_pes.join(df_wide, on="pe_id", how="left")

        # Select output columns
        meta_cols = ["pe_number", "program_name", "agency",
                     "budget_activity", "relevance_score",
                     "policy_context", "funding_trend"]
        funding_cols = [c for c in df_result.columns if c.startswith("FY")]
        out_cols = [c for c in meta_cols + sorted(funding_cols) if c in df_result.columns]

        return df_result.select(out_cols).sort("relevance_score", descending=True)

    def nds_priority_mapping(
        self,
        nds_year: int,
        top_pes_per_section: int = 5,
    ) -> pl.DataFrame:
        """
        Map each NDS section to its top matched PEs with funding trajectory.
        Returns a comprehensive mapping DataFrame.

        Example:
            df = linker.nds_priority_mapping(nds_year=2022)
        """
        # Get all NDS chunks for this year
        nds_chunks = self.session.execute(
            select(
                PolicyChunk.id,
                PolicyChunk.section_title,
                PolicyChunk.text,
            )
            .join(PolicyDocument)
            .where(
                PolicyDocument.doc_type == "NDS",
                PolicyDocument.year == nds_year,
            )
            .order_by(PolicyChunk.chunk_index)
        ).all()

        if not nds_chunks:
            logger.warning(f"No NDS chunks found for year {nds_year}")
            return pl.DataFrame()

        # Deduplicate by section_title — one representative chunk per section
        seen_sections: set[str] = set()
        representative_chunks: list[tuple[int, str, str]] = []
        for chunk_id, section_title, text in nds_chunks:
            key = (section_title or "").strip()
            if key and key not in seen_sections:
                seen_sections.add(key)
                representative_chunks.append((chunk_id, key, text))

        if not representative_chunks:
            representative_chunks = [(r[0], r[1] or "", r[2]) for r in nds_chunks[:20]]

        logger.info(
            f"NDS {nds_year}: mapping {len(representative_chunks)} "
            f"sections to PEs ..."
        )

        all_rows = []
        for chunk_id, section_title, text in tqdm(
            representative_chunks, desc=f"NDS {nds_year} sections"
        ):
            query = f"{section_title}: {text[:300]}"
            if self._pe_embeddings is None:
                continue

            q_emb = self.embedder.model.encode(
                query, convert_to_tensor=True, normalize_embeddings=True
            )
            scores = util.cos_sim(q_emb, self._pe_embeddings)[0]
            top = torch.topk(scores, k=min(top_pes_per_section, len(self._pe_ids)))

            for score_t, idx_t in zip(top.values, top.indices):
                score = score_t.item()
                if score < 0.35:
                    continue
                idx = idx_t.item()
                all_rows.append({
                    "nds_year":        nds_year,
                    "nds_section":     section_title[:200],
                    "pe_number":       self._pe_numbers[idx],
                    "program_name":    self._pe_names[idx],
                    "agency":          self._pe_agencies[idx],
                    "budget_activity": self._pe_bas[idx],
                    "relevance_score": round(score, 4),
                })

        if not all_rows:
            return pl.DataFrame()

        return (
            pl.DataFrame(all_rows)
            .sort(["nds_section", "relevance_score"], descending=[False, True])
        )

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _get_latest_funding(
        self, pe_ids: list[int]
    ) -> list[dict]:
        """Get latest BY Request amount and simple trend for a list of PE IDs."""
        results = []
        for pe_id in pe_ids:
            rows = self.session.execute(
                select(
                    FundingLine.fiscal_year,
                    FundingLine.amount_thousands,
                )
                .where(
                    FundingLine.program_element_id == pe_id,
                    FundingLine.funding_type == "BY Request",
                )
                .order_by(FundingLine.fiscal_year)
            ).all()

            if not rows:
                results.append({
                    "pe_id": pe_id,
                    "latest_fy": None,
                    "latest_by_request_m": None,
                    "trend": "N/A",
                })
                continue

            latest_fy  = rows[-1][0]
            latest_amt = rows[-1][1] / 1_000  # $K -> $M
            if len(rows) >= 2:
                first_amt = rows[0][1] / 1_000
                if latest_amt > first_amt * 1.05:
                    trend = "↑"
                elif latest_amt < first_amt * 0.95:
                    trend = "↓"
                else:
                    trend = "→"
            else:
                trend = "→"

            results.append({
                "pe_id": pe_id,
                "latest_fy": latest_fy,
                "latest_by_request_m": round(latest_amt, 2),
                "trend": trend,
            })
        return results


# ── CLI ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse
    from storage.db import get_engine, get_session_factory, init_db

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    _HERE2 = Path(__file__).parent.parent
    DEFAULT_DB = f"sqlite:///{_HERE2}/data/processed/usg_budgets.db"

    cli = argparse.ArgumentParser(description="Policy ↔ Budget cross-reference analysis")
    cli.add_argument("--db", default=DEFAULT_DB)
    sub = cli.add_subparsers(dest="cmd")

    # policy-to-pe
    p2p = sub.add_parser("policy-to-pe", help="Find PEs matching a policy topic")
    p2p.add_argument("query", help="Policy topic e.g. 'hypersonic strike'")
    p2p.add_argument("--type", nargs="+", help="Doc types: NDS NSS NDAA")
    p2p.add_argument("--year", type=int, help="Document year")
    p2p.add_argument("--n", type=int, default=10)

    # pe-to-policy
    pe2p = sub.add_parser("pe-to-policy", help="Find policy chunks for a PE")
    pe2p.add_argument("pe", help="PE number or program name fragment")
    pe2p.add_argument("--type", nargs="+")
    pe2p.add_argument("--n", type=int, default=10)

    # gap
    gap = sub.add_parser("gap", help="Gap analysis: policy priority vs funding")
    gap.add_argument("query", help="Policy topic")
    gap.add_argument("--start", type=int, default=2020)
    gap.add_argument("--end",   type=int, default=2026)
    gap.add_argument("--type", nargs="+")
    gap.add_argument("--n", type=int, default=10)

    # nds-map
    nds = sub.add_parser("nds-map", help="Map all NDS sections to PEs")
    nds.add_argument("--year", type=int, default=2022)

    args = cli.parse_args()
    if not args.cmd:
        cli.print_help()
        exit(0)

    engine = get_engine(args.db)
    init_db(engine)
    SessionFactory = get_session_factory(engine)

    with SessionFactory() as session:
        linker = PolicyLinker(session)

        if args.cmd == "policy-to-pe":
            df = linker.policy_to_pes(
                args.query, doc_type=args.type[0] if args.type else None,
                year=args.year, top_n=args.n,
            )
            if df.is_empty():
                print("No matches found.")
            else:
                print(df.to_pandas().to_string(index=False))

        elif args.cmd == "pe-to-policy":
            df = linker.pe_to_policy(
                args.pe, top_n=args.n,
                doc_type_filter=args.type,
            )
            if df.is_empty():
                print("No matches found.")
            else:
                print(df.select(["doc_type","year","section_title","score","text"]).to_pandas().to_string(index=False))

        elif args.cmd == "gap":
            df = linker.gap_analysis(
                args.query, start_fy=args.start, end_fy=args.end,
                doc_type_filter=args.type, top_n_pes=args.n,
            )
            if df.is_empty():
                print("No results.")
            else:
                print(df.to_pandas().to_string(index=False))

        elif args.cmd == "nds-map":
            df = linker.nds_priority_mapping(nds_year=args.year)
            if df.is_empty():
                print("No results.")
            else:
                out = _HERE2 / "data" / "processed" / f"nds_{args.year}_pe_mapping.csv"
                df.to_pandas().to_csv(out, index=False)
                print(f"Saved {len(df):,} rows to {out}")
                print(df.head(20).to_pandas().to_string(index=False))