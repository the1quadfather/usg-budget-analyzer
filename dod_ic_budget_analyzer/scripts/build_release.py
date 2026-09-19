"""Build a verified, self-contained data release bundle."""

from __future__ import annotations

import argparse
from contextlib import closing
from datetime import date, datetime, timezone
import gzip
import hashlib
import json
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import tempfile


APP_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = APP_DIR.parent
sys.path.insert(0, str(APP_DIR))

import config
from storage.db import get_engine


DATA_TABLES = (
    "source_documents",
    "program_elements",
    "funding_lines",
    "procurement_lines",
    "pe_execution",
    "pe_congressional_actions",
    "pe_narratives",
    "pe_accomplishments",
    "pe_lineage",
    "narrative_facts",
    "narrative_extractions",
)
RUNTIME_TABLES = (
    "ai_cache",
    "ai_spend",
    "ai_user_history",
    "search_log",
)
COMPLIANCE_QUERY = """
SELECT COUNT(*)
FROM ai_cache
WHERE task IN ('find_open_source_hits', 'annual_signal')
"""


def archive_checks(connection: sqlite3.Connection) -> list[str]:
    """Return failures that make a database unsafe to publish."""
    failures = []
    runtime_counts = {}
    for table in RUNTIME_TABLES:
        count = connection.execute(
            f"SELECT COUNT(*) FROM {table}"
        ).fetchone()[0]
        runtime_counts[table] = count
        if count:
            failures.append(f"{table} contains {count} runtime row(s)")

    grounded_count = connection.execute(COMPLIANCE_QUERY).fetchone()[0]
    if grounded_count:
        ai_cache_failure = (
            f"ai_cache contains {runtime_counts['ai_cache']} runtime row(s)"
        )
        failures.remove(ai_cache_failure)
        failures.append(
            f"{ai_cache_failure}; compliance query found "
            f"{grounded_count} grounded result(s)"
        )
    return failures


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def manifest_for(
    connection: sqlite3.Connection,
    archive_path: Path,
) -> dict:
    """Describe the verified archive and its provenance rows."""
    tables = {
        table: connection.execute(
            f"SELECT COUNT(*) FROM {table}"
        ).fetchone()[0]
        for table in DATA_TABLES
    }
    runtime_tables = {
        table: connection.execute(
            f"SELECT COUNT(*) FROM {table}"
        ).fetchone()[0]
        for table in RUNTIME_TABLES
    }
    source_documents = [
        {
            "filename": row[0],
            "document_type": row[1],
            "source_url": row[2],
            "content_hash": row[3],
        }
        for row in connection.execute(
            """
            SELECT filename, document_type, source_url, content_hash
            FROM source_documents
            ORDER BY filename
            """
        )
    ]
    return {
        "built_at": datetime.now(timezone.utc).isoformat(),
        "archive_sha256": _sha256(archive_path),
        "archive_bytes": archive_path.stat().st_size,
        "tables": tables,
        "runtime_tables": runtime_tables,
        "source_documents": source_documents,
    }


def release_notes(
    previous: dict | None,
    current: dict,
    date: str,
) -> str:
    """Render release notes from current and previous manifests."""
    lines = [
        f"# USG budget data release — {date}",
        "",
        f"Archive SHA-256: `{current['archive_sha256']}`",
        "",
        "## Row counts",
        "",
        "| Table | Rows |",
        "|---|---:|",
    ]
    for table, count in current["tables"].items():
        lines.append(f"| `{table}` | {count:,} |")
    for table, count in current.get("runtime_tables", {}).items():
        lines.append(f"| `{table}` | {count:,} |")

    if previous is None:
        lines.extend([
            "",
            "## Changes",
            "",
            "First release; no previous manifest to compare.",
        ])
    else:
        previous_date = previous.get("_release_date")
        if previous_date is None:
            previous_date = str(previous.get("built_at", "previous release"))[:10]
        lines.extend([
            "",
            f"## Changes since {previous_date}",
            "",
        ])
        changes = []
        previous_tables = previous.get("tables", {})
        for table in sorted(set(previous_tables) | set(current["tables"])):
            before = previous_tables.get(table, 0)
            after = current["tables"].get(table, 0)
            if before != after:
                changes.append(
                    f"{table}: {before} -> {after} ({after - before:+d})"
                )
        if changes:
            lines.extend(["| Change |", "|---|"])
            lines.extend(f"| {change} |" for change in changes)
        else:
            lines.append("No table row counts changed.")
    return "\n".join(lines) + "\n"


def _release_date(value: str) -> str:
    try:
        parsed = date.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("date must use YYYY-MM-DD") from exc
    if parsed.isoformat() != value:
        raise argparse.ArgumentTypeError("date must use YYYY-MM-DD")
    return value


def _previous_manifest(release_root: Path, current_dir: Path) -> dict | None:
    manifests = sorted(
        release_root.glob("usg-budgets-*/manifest.json"),
        key=lambda path: path.parent.name,
        reverse=True,
    )
    for path in manifests:
        if path.parent == current_dir:
            continue
        previous = json.loads(path.read_text(encoding="utf-8"))
        previous["_release_date"] = path.parent.name.removeprefix("usg-budgets-")
        return previous
    return None


def _reset_working_database() -> None:
    database = config.PROCESSED_DIR / "usg_budgets.db"
    engine = get_engine(f"sqlite:///{database.resolve().as_posix()}")
    engine.dispose()
    subprocess.run(
        [sys.executable, "-m", "analysis.ai_budget", "--reset-runtime"],
        cwd=APP_DIR,
        check=True,
    )


def _decompress_archive(archive: Path, destination: Path) -> None:
    with gzip.open(archive, "rb") as source, destination.open("wb") as target:
        shutil.copyfileobj(source, target)


def _bundle_size(path: Path) -> int:
    return sum(item.stat().st_size for item in path.rglob("*") if item.is_file())


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--date",
        type=_release_date,
        default=datetime.now(timezone.utc).date().isoformat(),
    )
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    _reset_working_database()
    archive = config.PROCESSED_DIR / "usg_budgets.db.gz"
    with tempfile.TemporaryDirectory() as temp_dir:
        temporary_database = Path(temp_dir) / "usg_budgets.db"
        _decompress_archive(archive, temporary_database)
        with closing(sqlite3.connect(temporary_database)) as connection:
            failures = archive_checks(connection)
            if failures:
                print("Release archive checks failed:", file=sys.stderr)
                for failure in failures:
                    print(f"- {failure}", file=sys.stderr)
                return 1
            manifest = manifest_for(connection, archive)

    release_root = REPO_ROOT / "release"
    bundle = release_root / f"usg-budgets-{args.date}"
    if bundle.exists() and not args.force:
        print(
            f"Release bundle already exists: {bundle}. Use --force to overwrite it.",
            file=sys.stderr,
        )
        return 1
    previous = _previous_manifest(release_root, bundle)
    if bundle.exists():
        shutil.rmtree(bundle)
    bundle.mkdir(parents=True)

    parquet_files = sorted(config.PROCESSED_DIR.glob("r1_*.parquet"))
    if len(parquet_files) != 30:
        print(
            f"Expected 30 R-1 parquet files, found {len(parquet_files)}.",
            file=sys.stderr,
        )
        return 1
    artifacts = [
        archive,
        *parquet_files,
        config.PROCESSED_DIR / "rdte_deflators_fy2025.csv",
        REPO_ROOT / "DATA_DICTIONARY.md",
    ]
    for artifact in artifacts:
        shutil.copy2(artifact, bundle / artifact.name)

    (bundle / "manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    (bundle / "RELEASE_NOTES.md").write_text(
        release_notes(previous, manifest, args.date),
        encoding="utf-8",
    )
    print(f"Built release bundle: {bundle}")
    print(f"Total size: {_bundle_size(bundle):,} bytes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
