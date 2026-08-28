"""
parsing/r2_parser.py

Parses DoD R-2 justification book XML (the official DTIC jbook schema,
published alongside the PDF volumes for Defense-Wide components at
comptroller.war.gov) into narrative and accomplishment records.

Structure (verified against RDTE_Vol1_DARPA_PB_2027.xml):
  JustificationBook
    r2:ProgramElementList/ProgramElement
      ProgramElementNumber / ProgramElementTitle / AppropriationName / ...
      ProgramElementMissionDescription          <- PE-level narrative
      ProjectList/Project
        ProjectNumber / ProjectTitle
        R2aExhibit
          ProjectMissionDescription             <- project-level narrative
          AccomplishmentPlannedProgramList/AccomplishmentPlannedProgram(s)
            Accomplishment...
              PriorYear|CurrentYear|BudgetYear* <- Funding ($M) + Text

Outputs two DataFrames:
  narratives:      pe_number, agency, fiscal_year, project_number,
                   project_title, description, source_file
                   (project_number == "" for the PE-level row)
  accomplishments: pe_number, agency, fiscal_year, project_number, title,
                   year_label, funding_millions, text, source_file

Tag matching is namespace-agnostic (localname-based) so schema-version
changes across years/components don't break the parse.
"""

import logging
import re
import xml.etree.ElementTree as ET
from pathlib import Path

import pandas as pd

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))
import config

try:
    from parsing.r1_parser import NativeR1Parser
except ImportError:
    from r1_parser import NativeR1Parser

logger = logging.getLogger(__name__)

# The only component strings program_elements uses; anything else is an
# ingestion artifact, never a real agency.
KNOWN_COMPONENTS = frozenset({
    "Army", "Navy", "Air Force", "Space Force", "Defense-Wide", "OT&E",
})

# Year buckets under Accomplishment (actuals) and PlannedProgram (plans)
# -> (label, offset from budget cycle year). BudgetYearOneBase is skipped:
# it duplicates BudgetYearOne in the post-OCO era.
YEAR_BUCKETS = {
    "PriorYear":     ("PY", -2),
    "CurrentYear":   ("CY", -1),
    "BudgetYear":    ("BY", 0),
    "BudgetYearOne": ("BY", 0),
}


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _find(elem, name):
    """First descendant-or-child with the given localname (depth-first)."""
    for e in elem.iter():
        if _local(e.tag) == name:
            return e
    return None


def _children(elem, name):
    return [c for c in elem if _local(c.tag) == name]


def _text(elem, name) -> str:
    """Full text content of the first child tree matching localname."""
    node = _find(elem, name)
    if node is None:
        return ""
    return re.sub(r"\s+", " ", "".join(node.itertext())).strip()


def _direct_text(elem, name) -> str:
    for c in elem:
        if _local(c.tag) == name:
            return re.sub(r"\s+", " ", "".join(c.itertext())).strip()
    return ""


class R2Parser:
    """Parses one jbook XML file into narrative + accomplishment frames."""

    def parse(self, xml_path: Path) -> dict[str, pd.DataFrame]:
        xml_path = Path(xml_path)
        tree = ET.parse(xml_path)
        root = tree.getroot()

        budget_year = _text(root, "BudgetYear")
        fiscal_year = int(budget_year) if budget_year.isdigit() else 0

        narratives, accomplishments = [], []
        pe_elems = [e for e in root.iter() if _local(e.tag) == "ProgramElement"]
        for pe in pe_elems:
            pe_number = _direct_text(pe, "ProgramElementNumber")
            if not pe_number:
                continue
            pe_title = _direct_text(pe, "ProgramElementTitle")
            appropriation = _direct_text(pe, "AppropriationName")
            agency = NativeR1Parser._normalise_component(appropriation or "Defense-Wide")
            # _normalise_component falls back to raw.title() for anything it does
            # not recognise, so an appropriation name leaks through as an agency
            # -- that is how 'Creating Helpful Incentives To Produce
            # Semi-Conductors (Chips) For America' ended up filed as a component
            # for three PEs. The codebase joins on (pe_number, agency), so a
            # bogus agency silently orphans every downstream row. This feed is
            # Defense-Wide, so clamp anything unrecognised to that.
            if agency not in KNOWN_COMPONENTS:
                logger.debug(f"{pe_number}: unrecognised component "
                             f"{agency!r} from {appropriation!r}; using Defense-Wide")
                agency = "Defense-Wide"
            fy = fiscal_year or int(_direct_text(pe, "BudgetYear") or 0)

            common = {
                "pe_number": pe_number,
                "agency": agency,
                "fiscal_year": fy,
                "source_file": xml_path.name,
            }

            pe_mission = _text(pe, "ProgramElementMissionDescription")
            if pe_mission:
                narratives.append({
                    **common,
                    "project_number": "",
                    "project_title": pe_title,
                    "description": pe_mission,
                })

            for project in (e for e in pe.iter() if _local(e.tag) == "Project"):
                proj_number = _direct_text(project, "ProjectNumber")
                proj_title = _direct_text(project, "ProjectTitle")
                proj_mission = _text(project, "ProjectMissionDescription")
                if proj_mission:
                    narratives.append({
                        **common,
                        "project_number": proj_number,
                        "project_title": proj_title,
                        "description": proj_mission,
                    })

                for acc_program in (e for e in project.iter()
                                    if _local(e.tag) == "AccomplishmentPlannedProgram"):
                    acc_title = _direct_text(acc_program, "Title")
                    # Actuals live under Accomplishment; CY/BY plans under
                    # PlannedProgram - both carry Funding + Text buckets.
                    for holder in (e for e in acc_program.iter()
                                   if _local(e.tag) in ("Accomplishment",
                                                        "PlannedProgram")):
                        for bucket in holder:
                            bucket_name = _local(bucket.tag)
                            if bucket_name not in YEAR_BUCKETS:
                                continue
                            label, offset = YEAR_BUCKETS[bucket_name]
                            funding_raw = _direct_text(bucket, "Funding")
                            try:
                                funding = float(funding_raw.replace(",", ""))
                            except ValueError:
                                funding = None
                            text = _direct_text(bucket, "Text")
                            if not text and funding is None:
                                continue
                            accomplishments.append({
                                **common,
                                "project_number": proj_number,
                                "title": acc_title,
                                "year_label": label,
                                "accomplishment_fy": fy + offset if fy else None,
                                "funding_millions": funding,
                                "text": text,
                            })

        logger.info(
            f"{xml_path.name}: {len(pe_elems)} PEs -> "
            f"{len(narratives)} narratives, {len(accomplishments)} accomplishments"
        )
        return {
            "narratives": pd.DataFrame(narratives),
            "accomplishments": pd.DataFrame(accomplishments),
        }

    def parse_directory(self, directory: Path) -> dict[str, pd.DataFrame]:
        """Parse every jbook XML in a directory and concatenate results."""
        frames = {"narratives": [], "accomplishments": []}
        for xml_path in sorted(Path(directory).glob("*.xml")):
            try:
                result = self.parse(xml_path)
                for key in frames:
                    if not result[key].empty:
                        frames[key].append(result[key])
            except Exception as e:
                logger.error(f"Failed to parse {xml_path.name}: {e}")
        return {
            key: (pd.concat(dfs, ignore_index=True) if dfs else pd.DataFrame())
            for key, dfs in frames.items()
        }


if __name__ == "__main__":
    import argparse

    logging.basicConfig(level="INFO",
                        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    ap = argparse.ArgumentParser(description="Parse R-2 jbook XML files.")
    ap.add_argument("--file", type=Path, help="Single jbook XML")
    ap.add_argument("--dir", type=Path, help="Directory of jbook XMLs")
    args = ap.parse_args()

    parser = R2Parser()
    result = parser.parse(args.file) if args.file else parser.parse_directory(args.dir)
    for key, df in result.items():
        print(f"\n{key}: {len(df)} rows")
        if not df.empty:
            print(df.head(3).to_string())
