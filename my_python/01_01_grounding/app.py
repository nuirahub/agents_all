from __future__ import annotations

import json
import logging
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import requests

# Ensure parent directory (`my_python`) is on sys.path so we can import shared config and helpers.
PARENT_DIR = Path(__file__).resolve().parents[1]
if str(PARENT_DIR) not in sys.path:
    sys.path.insert(0, str(PARENT_DIR))

from config import CONFIG  # noqa: E402
from helpers import extract_response_text  # noqa: E402

logger = logging.getLogger(__name__)


ROOT_DIR = Path(__file__).resolve().parents[2]
PROJECT_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = PROJECT_DIR / "output"

DEFAULT_NOTES_FILE = ROOT_DIR / "my_python" / "01_01_grounding" / "notes" / "notes.md"

MODEL_EXTRACT = CONFIG.resolve_model_for_provider("gpt-5.4")

CONCEPT_CATEGORIES = [
    "claim",
    "result",
    "method",
    "metric",
    "resource",
    "definition",
    "term",
    "entity",
    "reference",
]

EXTRACTION_SCHEMA: dict[str, Any] = {
    "type": "json_schema",
    "name": "concept_extraction",
    "strict": True,
    "schema": {
        "type": "object",
        "description": "Extracted concepts from a single paragraph.",
        "properties": {
            "concepts": {
                "type": "array",
                "description": (
                    "Extracted claims and terms for this paragraph. "
                    "Each surfaceForm should be a short key phrase (3-12 words), "
                    "not a full sentence. Empty array if nothing qualifies."
                ),
                "items": {
                    "type": "object",
                    "properties": {
                        "label": {
                            "type": "string",
                            "description": (
                                "Canonical name for the claim or term being extracted."
                            ),
                        },
                        "category": {
                            "type": "string",
                            "enum": CONCEPT_CATEGORIES,
                            "description": "Concept category from the allowed taxonomy.",
                        },
                        "needsSearch": {
                            "type": "boolean",
                            "description": (
                                "True when verification or extra context would help "
                                "via web search."
                            ),
                        },
                        "searchQuery": {
                            "type": ["string", "null"],
                            "description": (
                                "Search query to verify/expand this concept. "
                                "Null if needsSearch is false."
                            ),
                        },
                        "reason": {
                            "type": "string",
                            "description": (
                                "Brief justification for why this concept was extracted."
                            ),
                        },
                        "surfaceForms": {
                            "type": "array",
                            "items": {"type": "string"},
                            "minItems": 1,
                            "description": (
                                "Short key phrases (3-12 words) copied exactly "
                                "from the paragraph. NOT entire sentences. "
                                "Never include markdown syntax like # or ##."
                            ),
                        },
                    },
                    "required": [
                        "label",
                        "category",
                        "needsSearch",
                        "searchQuery",
                        "reason",
                        "surfaceForms",
                    ],
                    "additionalProperties": False,
                },
            }
        },
        "required": ["concepts"],
        "additionalProperties": False,
    },
}


EXTRACTION_GUIDELINES = (
    "Goal: extract verifiable claims and key terms that benefit from grounding "
    "via web search.\n\n"
    "Categories:\n"
    "- claim: a verifiable statement with facts, dates, counts, or attributions\n"
    "- definition: an explicit definition or explanation of a term\n"
    "- term: domain-specific concept or jargon worth grounding\n"
    "- entity: a named person, organization, product central to the paragraph\n"
    "- reference: a cited work, paper, or external source\n"
    "- result: a reported finding or outcome\n"
    "- method: a procedure, algorithm, or process\n"
    "- metric: a quantitative measure or threshold\n"
    "- resource: a dataset, tool, or system\n\n"
    "surfaceForms rules (CRITICAL):\n"
    "- surfaceForms are SHORT KEY PHRASES, NOT entire sentences.\n"
    "- Ideal length: 3-12 words. Never exceed 15 words.\n"
    "- Extract the minimal phrase that uniquely identifies the claim.\n"
    "- NEVER include markdown syntax (#, ##, *, etc.) in surfaceForms.\n"
)


@dataclass
class ParagraphConcepts:
    index: int
    text: str
    concepts: list[dict[str, Any]]
    raw_count: int


def split_paragraphs(markdown: str) -> list[str]:
    parts = [p.strip() for p in markdown.split("\n\n")]
    return [p for p in parts if p]


def detect_paragraph_type(paragraph: str) -> str:
    stripped = paragraph.lstrip()
    if stripped.startswith("#"):
        return "header"
    return "body"


def target_concept_count(paragraph_type: str) -> int:
    return 3 if paragraph_type == "header" else 6


def build_extract_prompt(
    paragraph: str, index: int, total: int, paragraph_type: str, target_count: int
) -> str:
    return (
        "You extract concepts and topics from a single paragraph.\n"
        "Focus entirely on this paragraph. Return JSON only, matching the schema.\n\n"
        "<guidelines>\n"
        f"{EXTRACTION_GUIDELINES}\n"
        "</guidelines>\n\n"
        f"Document context: paragraph {index + 1} of {total}\n"
        f"Paragraph type: {paragraph_type}\n"
        f"Target concepts: {target_count} (fewer for headers, more for body)\n\n"
        "--- Paragraph ---\n"
        f"{paragraph}"
    )


def extract_single_paragraph(
    paragraph: str, index: int, total: int
) -> ParagraphConcepts:
    paragraph_type = detect_paragraph_type(paragraph)
    target_count = target_concept_count(paragraph_type)

    input_text = build_extract_prompt(
        paragraph=paragraph,
        index=index,
        total=total,
        paragraph_type=paragraph_type,
        target_count=target_count,
    )

    body = {
        "model": MODEL_EXTRACT,
        "input": input_text,
        "text": {"format": EXTRACTION_SCHEMA},
        "reasoning": {"effort": "medium"},
    }

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {CONFIG.api_key}",
        **CONFIG.extra_api_headers,
    }

    logger.info("Extracting concepts for paragraph %s/%s", index + 1, total)

    response = requests.post(
        CONFIG.responses_api_endpoint,
        json=body,
        headers=headers,
        timeout=180,
    )

    try:
        data = response.json()
    except ValueError:
        response.raise_for_status()
        raise

    if (not response.ok) or (isinstance(data, dict) and data.get("error")):
        message = (
            data.get("error", {}).get("message")
            if isinstance(data, dict)
            else f"Request failed with status {response.status_code}"
        )
        logger.error("Extraction request failed: %s", message)
        raise RuntimeError(
            message or f"Request failed with status {response.status_code}"
        )

    output_text = extract_response_text(data)
    if not output_text:
        logger.error("Missing text output in API response")
        raise RuntimeError("Missing text output in API response")

    try:
        parsed = json.loads(output_text)
    except json.JSONDecodeError as exc:  # noqa: TRY003
        logger.error("Failed to parse JSON for paragraph %s: %s", index + 1, exc)
        raise RuntimeError(
            "Model returned invalid JSON for concept extraction"
        ) from exc

    concepts = parsed.get("concepts") or []
    if not isinstance(concepts, list):
        logger.error("Field 'concepts' is not a list in paragraph %s", index + 1)
        raise RuntimeError("Invalid JSON structure: 'concepts' must be a list")

    return ParagraphConcepts(
        index=index,
        text=paragraph,
        concepts=concepts,
        raw_count=len(concepts),
    )


def extract_concepts(markdown: str, source_file: Path) -> dict[str, Any]:
    paragraphs = split_paragraphs(markdown)

    print(f"\n📄 Source: {source_file}")
    print(f"   Paragraphs: {len(paragraphs)}\n")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    concepts_path = OUTPUT_DIR / "concepts.json"

    results: list[ParagraphConcepts] = []

    for idx, paragraph in enumerate(paragraphs):
        if not paragraph.strip():
            continue
        result = extract_single_paragraph(paragraph, idx, len(paragraphs))
        results.append(result)
        print(
            f"  ✓ [{idx + 1}] {len(result.concepts)} concepts (raw {result.raw_count})"
        )

    concepts_data: dict[str, Any] = {
        "sourceFile": str(source_file),
        "model": MODEL_EXTRACT,
        "paragraphs": [
            {
                "index": r.index,
                "text": r.text,
                "concepts": r.concepts,
            }
            for r in results
        ],
    }
    concepts_data["paragraphCount"] = len(concepts_data["paragraphs"])
    concepts_data["conceptCount"] = sum(
        len(p["concepts"]) for p in concepts_data["paragraphs"]
    )

    with concepts_path.open("w", encoding="utf-8") as f:
        json.dump(concepts_data, f, ensure_ascii=False, indent=2)

    print(f"\n✅ Done! Concepts written to: {concepts_path}")
    return concepts_data


def confirm_run() -> None:
    print("\n⚠️  UWAGA: Uruchomienie tego skryptu może zużyć znaczną ilość tokenów.")
    print(
        "   Jeśli nie chcesz go uruchamiać, możesz sprawdzić gotowy wynik w wersji JS."
    )
    answer = input("Czy chcesz kontynuować? (yes/y): ")
    normalized = answer.strip().lower()
    if normalized not in {"yes", "y"}:
        print("Przerwano.")
        raise SystemExit(0)


def parse_cli_args() -> tuple[Path, bool]:
    args = sys.argv[1:]
    force = "--force" in args
    non_flags = [a for a in args if not a.startswith("--")]

    if non_flags:
        source = Path(non_flags[0]).resolve()
    else:
        source = DEFAULT_NOTES_FILE

    return source, force


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    confirm_run()

    source_file, _force = parse_cli_args()

    if not source_file.is_file():
        raise SystemExit(f"Input markdown file not found: {source_file}")

    markdown = source_file.read_text(encoding="utf-8")
    extract_concepts(markdown, source_file)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:  # noqa: BLE001
        logger.exception("Unhandled error in main: %s", exc)
        print(f"Error: {exc}", file=sys.stderr)
        raise SystemExit(1)
