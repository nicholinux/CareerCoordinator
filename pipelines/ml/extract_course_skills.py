"""Extract controlled skills from normalized UGA course records."""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any


ROOT_DIR = Path(__file__).resolve().parents[2]
DEFAULT_COURSES_PATH = ROOT_DIR / "data" / "processed" / "uga" / "courses" / "courses_normalized.json"
DEFAULT_TAXONOMY_PATH = ROOT_DIR / "data" / "processed" / "skills" / "skill_taxonomy.json"
DEFAULT_OUTPUT_PATH = ROOT_DIR / "data" / "processed" / "skills" / "course_skills.json"

TEXT_FIELDS = (
    ("title", 0.95),
    ("description", 0.85),
    ("course_objective", 0.8),
    ("topic_outline", 0.78),
    ("prerequisites", 0.6),
)

COURSE_CODE_RE = re.compile(r"^(?P<subject>[A-Z]{2,5})(?:\([A-Z()]+\))*\s+(?P<number>[0-9A-Z/\-]+)$")


@dataclass(frozen=True)
class SkillTerm:
    skill_id: str
    label: str
    category_id: str
    category_label: str
    term: str
    term_type: str


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as file:
        return json.load(file)


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as file:
        json.dump(payload, file, indent=2, ensure_ascii=False)
        file.write("\n")


def normalize_space(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    return re.sub(r"\s+", " ", value.strip())


def course_id_from_code(value: Any) -> str:
    normalized = normalize_space(value).upper()
    match = COURSE_CODE_RE.match(normalized)
    if not match:
        return normalized.replace(" ", "_")

    subject = match.group("subject")
    number = match.group("number").split("/")[0].split("-")[0]
    if number.endswith("E"):
        number = number[:-1]
    return f"{subject}_{number}"


def compile_term_pattern(term: str) -> re.Pattern[str]:
    escaped = re.escape(term.lower())
    return re.compile(rf"(?<![a-z0-9+/#]){escaped}(?![a-z0-9+/#])", re.IGNORECASE)


def flatten_taxonomy(taxonomy: dict[str, Any]) -> list[SkillTerm]:
    terms: list[SkillTerm] = []
    seen: set[tuple[str, str]] = set()

    for category in taxonomy.get("categories", []):
        category_id = category.get("category_id", "")
        category_label = category.get("label", "")
        for skill in category.get("skills", []):
            skill_id = skill.get("skill_id", "")
            label = skill.get("label", "")
            label_key = (skill_id, label.lower())
            if skill_id and label and label_key not in seen:
                seen.add(label_key)
                terms.append(
                    SkillTerm(
                        skill_id=skill_id,
                        label=label,
                        category_id=category_id,
                        category_label=category_label,
                        term=label,
                        term_type="label",
                    )
                )

            for alias in skill.get("aliases", []):
                alias = normalize_space(alias)
                alias_key = (skill_id, alias.lower())
                if skill_id and alias and alias_key not in seen:
                    seen.add(alias_key)
                    terms.append(
                        SkillTerm(
                            skill_id=skill_id,
                            label=label,
                            category_id=category_id,
                            category_label=category_label,
                            term=alias,
                            term_type="alias",
                        )
                    )

    return sorted(terms, key=lambda item: len(item.term), reverse=True)


def evidence_snippet(text: str, start: int, end: int, radius: int = 120) -> str:
    left = max(0, start - radius)
    right = min(len(text), end + radius)
    snippet = normalize_space(text[left:right])
    if left > 0:
        snippet = f"...{snippet}"
    if right < len(text):
        snippet = f"{snippet}..."
    return snippet


def find_skill_matches(course: dict[str, Any], terms: list[SkillTerm]) -> dict[str, dict[str, Any]]:
    matches: dict[str, dict[str, Any]] = {}

    for field_name, base_confidence in TEXT_FIELDS:
        text = normalize_space(course.get(field_name))
        if not text:
            continue

        lower_text = text.lower()
        for term in terms:
            pattern = compile_term_pattern(term.term)
            for match in pattern.finditer(lower_text):
                record = matches.setdefault(
                    term.skill_id,
                    {
                        "skill_id": term.skill_id,
                        "label": term.label,
                        "category_id": term.category_id,
                        "category_label": term.category_label,
                        "confidence": 0.0,
                        "evidence": [],
                    },
                )
                term_bonus = 0.03 if term.term_type == "label" else 0.0
                confidence = min(base_confidence + term_bonus, 0.99)
                record["confidence"] = max(record["confidence"], confidence)

                evidence = {
                    "field": field_name,
                    "matched_text": text[match.start() : match.end()],
                    "matched_term": term.term,
                    "term_type": term.term_type,
                    "snippet": evidence_snippet(text, match.start(), match.end()),
                }
                if evidence not in record["evidence"]:
                    record["evidence"].append(evidence)

    for record in matches.values():
        repeated_evidence_bonus = min(max(len(record["evidence"]) - 1, 0) * 0.02, 0.08)
        record["confidence"] = round(min(record["confidence"] + repeated_evidence_bonus, 0.99), 2)
        record["evidence"] = record["evidence"][:5]

    return matches


def extraction_status(skills: list[dict[str, Any]], review_threshold: float) -> str:
    if not skills:
        return "no_skill_match"
    if any(skill["confidence"] < review_threshold for skill in skills):
        return "needs_review"
    return "parsed"


def extract_course_skills(courses: list[dict[str, Any]], taxonomy: dict[str, Any]) -> dict[str, Any]:
    terms = flatten_taxonomy(taxonomy)
    policy = taxonomy.get("extraction_policy", {})
    low_confidence_threshold = float(policy.get("low_confidence_threshold", 0.55))
    review_threshold = float(policy.get("review_threshold", 0.7))
    allowed_subjects = set(taxonomy.get("metadata", {}).get("allowed_subject_scope", []))

    course_skill_records = []
    skill_ids_seen: set[str] = set()
    low_confidence_count = 0
    no_match_count = 0

    for course in courses:
        if allowed_subjects and course.get("subject") not in allowed_subjects:
            continue

        matches = find_skill_matches(course, terms)
        skills = sorted(matches.values(), key=lambda item: (-item["confidence"], item["skill_id"]))
        skill_ids_seen.update(skill["skill_id"] for skill in skills)
        low_confidence_skills = [
            skill["skill_id"] for skill in skills if low_confidence_threshold <= skill["confidence"] < review_threshold
        ]
        if low_confidence_skills:
            low_confidence_count += 1
        if not skills:
            no_match_count += 1

        course_skill_records.append(
            {
                "course_id": course_id_from_code(course.get("course_code")),
                "course_code": course.get("course_code"),
                "subject": course.get("subject"),
                "title": course.get("title"),
                "skills": skills,
                "low_confidence_skill_ids": low_confidence_skills,
                "rejected_skill_labels": [],
                "parse_status": extraction_status(skills, review_threshold),
            }
        )

    return {
        "metadata": {
            "source_courses": str(DEFAULT_COURSES_PATH.relative_to(ROOT_DIR)),
            "source_taxonomy": str(DEFAULT_TAXONOMY_PATH.relative_to(ROOT_DIR)),
            "course_count": len(course_skill_records),
            "courses_with_skills": len(course_skill_records) - no_match_count,
            "courses_without_skill_matches": no_match_count,
            "courses_needing_review": low_confidence_count,
            "unique_skill_count": len(skill_ids_seen),
            "allow_only_defined_skill_ids": bool(policy.get("allow_only_defined_skill_ids", True)),
            "reject_unknown_skills": bool(policy.get("reject_unknown_skills", True)),
            "low_confidence_threshold": low_confidence_threshold,
            "review_threshold": review_threshold,
        },
        "course_skills": course_skill_records,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Extract controlled skills from normalized UGA courses.")
    parser.add_argument("--courses-path", type=Path, default=DEFAULT_COURSES_PATH)
    parser.add_argument("--taxonomy-path", type=Path, default=DEFAULT_TAXONOMY_PATH)
    parser.add_argument("--output-path", type=Path, default=DEFAULT_OUTPUT_PATH)
    args = parser.parse_args()

    courses = load_json(args.courses_path)
    taxonomy = load_json(args.taxonomy_path)
    payload = extract_course_skills(courses, taxonomy)

    payload["metadata"]["source_courses"] = str(args.courses_path)
    payload["metadata"]["source_taxonomy"] = str(args.taxonomy_path)
    write_json(args.output_path, payload)

    print(
        json.dumps(
            {
                "course_count": payload["metadata"]["course_count"],
                "courses_with_skills": payload["metadata"]["courses_with_skills"],
                "courses_needing_review": payload["metadata"]["courses_needing_review"],
                "unique_skill_count": payload["metadata"]["unique_skill_count"],
                "output_path": str(args.output_path),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
