"""Batch extraction of verified structured facts from PE-level narratives."""

import argparse
import hashlib
import re
import sys
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.exc import OperationalError

sys.path.insert(0, str(Path(__file__).parent.parent))

import config
from analysis.ai_budget import (
    AISpend,
    DB_URI,
    SpendLedger,
    budget_guard,
    report,
    session_factory,
    token_cost,
)
from analysis.oss_enricher import PROMPT_VERSIONS
from storage.db import (
    FACT_TYPES,
    NarrativeExtraction,
    NarrativeFact,
    PENarrative,
    get_engine,
    get_session_factory,
    narrative_fact_hash,
)


TASK = "extract_facts"
PROMPT_VERSION = PROMPT_VERSIONS[TASK]
NARRATIVE_TABLE = "pe_narratives"


def text_hash(text: str) -> str:
    """Return the full sha256 hex digest for source text."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _normalise_with_offsets(value: str) -> tuple[str, list[int]]:
    """Collapse whitespace and retain each output character's source offset."""
    normalised: list[str] = []
    offsets: list[int] = []
    pending_space: int | None = None
    for offset, char in enumerate(value):
        if char.isspace():
            if normalised:
                pending_space = offset
            continue
        if pending_space is not None:
            normalised.append(" ")
            offsets.append(pending_space)
            pending_space = None
        normalised.append(char)
        offsets.append(offset)
    return "".join(normalised), offsets


def locate_sentence(text: str, sentence: str) -> tuple[int, int] | None:
    """Locate a verbatim or whitespace-normalised sentence without fuzzing."""
    if not sentence:
        return None
    start = text.find(sentence)
    if start >= 0:
        return start, start + len(sentence)

    normalised_text, offsets = _normalise_with_offsets(text)
    normalised_sentence = re.sub(r"\s+", " ", sentence).strip()
    if not normalised_sentence:
        return None
    normalised_start = normalised_text.find(normalised_sentence)
    if normalised_start < 0:
        return None
    normalised_end = normalised_start + len(normalised_sentence)
    return offsets[normalised_start], offsets[normalised_end - 1] + 1


def verify_facts(raw_facts, text: str) -> tuple[list[dict], int]:
    """Keep only typed, non-empty facts backed by a source-text span."""
    kept: list[dict] = []
    dropped = 0
    for fact in raw_facts or []:
        if not isinstance(fact, dict):
            dropped += 1
            continue
        fact_type = fact.get("fact_type")
        value = fact.get("value")
        sentence = fact.get("sentence")
        if fact_type not in FACT_TYPES or not isinstance(value, str):
            dropped += 1
            continue
        value = value.strip()
        if not value or not isinstance(sentence, str):
            dropped += 1
            continue
        span = locate_sentence(text, sentence)
        if span is None:
            dropped += 1
            continue
        start, end = span
        kept.append({
            "fact_type": fact_type,
            "value": value,
            "sentence": text[start:end],
            "char_start": start,
            "char_end": end,
        })
    return kept, dropped


def build_worklist(session, *, limit: int,
                   fiscal_year: int | None = None) -> list[dict]:
    """Return the next distinct, unprocessed PE-level narrative texts."""
    completed_hashes: set[str] = set()
    completed_sources: set[tuple[str, int]] = set()
    try:
        completed = session.execute(
            select(
                NarrativeExtraction.narrative_table,
                NarrativeExtraction.narrative_id,
                NarrativeExtraction.text_hash,
            ).where(
                NarrativeExtraction.model == config.GEMINI_MODEL,
                NarrativeExtraction.prompt_version == PROMPT_VERSION,
            )
        ).all()
        completed_hashes = {row.text_hash for row in completed}
        completed_sources = {
            (row.narrative_table, row.narrative_id) for row in completed
        }
    except OperationalError as exc:
        if "no such table" not in str(exc).lower():
            raise
        session.rollback()

    query = select(PENarrative).where(PENarrative.project_number == "")
    if fiscal_year is not None:
        query = query.where(PENarrative.fiscal_year == fiscal_year)
    query = query.order_by(
        PENarrative.fiscal_year.desc(),
        PENarrative.pe_number,
        PENarrative.agency,
        PENarrative.id,
    )

    work: list[dict] = []
    seen: set[tuple[str, str, str]] = set()
    for narrative in session.execute(query).scalars():
        digest = text_hash(narrative.description)
        identity = (narrative.pe_number, narrative.agency, digest)
        if identity in seen:
            continue
        seen.add(identity)
        if ((NARRATIVE_TABLE, narrative.id) in completed_sources
                or digest in completed_hashes):
            continue
        work.append({
            "narrative_table": NARRATIVE_TABLE,
            "narrative_id": narrative.id,
            "pe_number": narrative.pe_number,
            "agency": narrative.agency,
            "fiscal_year": narrative.fiscal_year,
            "text": narrative.description,
        })
        if len(work) >= limit:
            break
    return work


def estimate_cost(work: list[dict],
                  model: str = config.GEMINI_MODEL) -> dict:
    """Return a worst-case token and cost estimate for a worklist."""
    estimate = {
        "items": len(work),
        "input_tokens": 0,
        "output_tokens": 0,
        "thought_tokens": 0,
        "usd": 0.0,
    }
    for item in work:
        input_tokens = len(item["text"]) // 4 + 300
        output_tokens = 200
        thought_tokens = 512
        estimate["input_tokens"] += input_tokens
        estimate["output_tokens"] += output_tokens
        estimate["thought_tokens"] += thought_tokens
        estimate["usd"] += token_cost(
            model, input_tokens, output_tokens, thought_tokens
        )
    return estimate


def write_results(session, item: dict, kept: list[dict], dropped: int,
                  usage: dict, cost: float) -> int:
    """Persist verified facts and the durable completion record once."""
    already_done = session.execute(
        select(NarrativeExtraction.id).where(
            NarrativeExtraction.narrative_table == item["narrative_table"],
            NarrativeExtraction.narrative_id == item["narrative_id"],
            NarrativeExtraction.model == config.GEMINI_MODEL,
            NarrativeExtraction.prompt_version == PROMPT_VERSION,
        )
    ).scalar_one_or_none()
    if already_done is not None:
        return 0

    inserted = 0
    for fact in kept:
        start = fact["char_start"]
        end = fact["char_end"]
        assert item["text"][start:end] == fact["sentence"]
        digest = narrative_fact_hash(
            item["narrative_table"],
            item["narrative_id"],
            fact["fact_type"],
            fact["value"],
            start,
            end,
        )
        exists = session.execute(
            select(NarrativeFact.id).where(
                NarrativeFact.content_hash == digest
            )
        ).scalar_one_or_none()
        if exists is not None:
            continue
        session.add(NarrativeFact(
            narrative_table=item["narrative_table"],
            narrative_id=item["narrative_id"],
            pe_number=item["pe_number"],
            agency=item["agency"],
            fiscal_year=item["fiscal_year"],
            fact_type=fact["fact_type"],
            value=fact["value"],
            sentence=fact["sentence"],
            char_start=start,
            char_end=end,
            model=config.GEMINI_MODEL,
            content_hash=digest,
        ))
        inserted += 1

    session.add(NarrativeExtraction(
        narrative_table=item["narrative_table"],
        narrative_id=item["narrative_id"],
        text_hash=text_hash(item["text"]),
        model=config.GEMINI_MODEL,
        prompt_version=PROMPT_VERSION,
        fact_count=len(kept),
        dropped_count=dropped,
        input_tokens=int(usage.get("input_tokens", 0)),
        output_tokens=int(usage.get("output_tokens", 0)),
        thought_tokens=int(usage.get("thought_tokens", 0)),
        est_cost_usd=cost,
    ))
    session.commit()
    return inserted


def _print_worklist(work: list[dict]) -> None:
    print("Worklist narratives:")
    for index, item in enumerate(work, 1):
        print(
            f"  {index:>2}. FY{item['fiscal_year']} "
            f"{item['pe_number']} [{item['agency']}] "
            f"{item['narrative_table']}:{item['narrative_id']} "
            f"sha256={text_hash(item['text'])[:16]}"
        )


def _latest_spend(after_id: int) -> AISpend | None:
    with session_factory()() as session:
        return session.execute(
            select(AISpend).where(
                AISpend.id > after_id,
                AISpend.task == TASK,
                AISpend.user_id == "extract",
            ).order_by(AISpend.id.desc())
        ).scalars().first()


def run(limit: int, dry_run: bool, fiscal_year: int | None = None) -> int:
    """Estimate or execute a bounded extraction batch."""
    if dry_run:
        factory = get_session_factory(get_engine(DB_URI))
    else:
        factory = session_factory()
    with factory() as session:
        work = build_worklist(
            session, limit=limit, fiscal_year=fiscal_year
        )

    estimate = estimate_cost(work)
    print(f"Worklist: {len(work)} narratives.")
    _print_worklist(work)
    print(
        "Estimate: "
        f"items={estimate['items']} "
        f"input_tokens={estimate['input_tokens']} "
        f"output_tokens={estimate['output_tokens']} "
        f"thought_tokens={estimate['thought_tokens']} "
        f"usd=${estimate['usd']:.4f}"
    )
    print(
        "Assumptions per narrative: input=len(text)//4+300, "
        "output=200, thought=512; token_cost uses configured model pricing."
    )
    if dry_run:
        print("DRY RUN - no API calls and no extraction writes.")
        return 0
    if not work:
        print("Nothing to extract.")
        return 0

    from analysis.oss_enricher import GeminiEnricher, available

    if not available():
        print("AI enrichment unavailable: install google-genai and set "
              f"one of {config.GEMINI_API_KEY_ENV_VARS}.")
        return 1
    guard = budget_guard(TASK, user_id="extract")
    if not guard.allowed:
        print(f"Refusing to start: {guard.message}")
        return 1

    with session_factory()() as session:
        last_spend_id = int(session.execute(
            select(func.coalesce(func.max(AISpend.id), 0))
        ).scalar() or 0)
    start_spend = SpendLedger.month_to_date(user_id="extract")
    enricher = GeminiEnricher()
    processed = facts_inserted = facts_dropped = failed = 0

    for index, item in enumerate(work, 1):
        result = enricher.extract_facts(
            item["narrative_table"],
            item["narrative_id"],
            item["text"],
            user_id="extract",
            allow_fresh=True,
            credits=len(work) + 1,
        )
        if result.blocked:
            print(f"[{index}/{len(work)}] stopped: {result.message}")
            failed += 1
            break

        spend = _latest_spend(last_spend_id)
        if spend is None:
            print(f"[{index}/{len(work)}] stopped: no spend ledger row.")
            failed += 1
            break
        last_spend_id = spend.id
        usage = {
            "input_tokens": spend.input_tokens,
            "output_tokens": spend.output_tokens,
            "thought_tokens": spend.thought_tokens,
        }
        raw_facts = (result.payload or {}).get("facts", [])
        kept, dropped = verify_facts(raw_facts, item["text"])
        with session_factory()() as session:
            inserted = write_results(
                session, item, kept, dropped, usage, spend.est_cost_usd
            )
        processed += 1
        facts_inserted += inserted
        facts_dropped += dropped
        state = "cached" if result.cached else "fresh"
        running_spend = (
            SpendLedger.month_to_date(user_id="extract") - start_spend
        )
        print(
            f"[{index}/{len(work)}] {state:<6} "
            f"kept={len(kept)} dropped={dropped} "
            f"inserted={inserted} spend=${running_spend:.4f} "
            f"{item['pe_number']} [{item['agency']}]"
        )

    spent = SpendLedger.month_to_date(user_id="extract") - start_spend
    print(
        f"Totals: processed={processed} facts_inserted={facts_inserted} "
        f"facts_dropped={facts_dropped} failed={failed} "
        f"spend=${spent:.4f}"
    )
    print()
    print(report())
    return 1 if failed else 0


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Extract verified facts from PE-level narratives."
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--run", action="store_true")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--fiscal-year", type=int)
    args = parser.parse_args()
    if args.run and args.limit is None:
        parser.error(
            "Pass --limit; the whole corpus is about 3.7 M input tokens and "
            "would exceed the monthly ceiling."
        )
    limit = 50 if args.limit is None else args.limit
    raise SystemExit(run(limit, args.dry_run, args.fiscal_year))


if __name__ == "__main__":
    main()
