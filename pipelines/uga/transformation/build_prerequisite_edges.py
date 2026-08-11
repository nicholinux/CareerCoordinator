"""Build directed prerequisite graph edges from UGA prerequisite rules."""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any


ROOT_DIR = Path(__file__).resolve().parents[3]
DEFAULT_COURSES_PATH = ROOT_DIR / "data" / "processed" / "uga" / "courses" / "courses_normalized.json"
DEFAULT_RULES_PATH = ROOT_DIR / "data" / "processed" / "uga" / "prerequisites" / "prerequisite_rules.json"
DEFAULT_OUTPUT_PATH = ROOT_DIR / "data" / "processed" / "uga" / "prerequisites" / "prerequisite_edges.json"

COURSE_CODE_RE = re.compile(r"\b(?P<subject>[A-Z]{2,5})\s+(?P<number>\d{4}[A-Z]?)\b")


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as file:
        return json.load(file)


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as file:
        json.dump(payload, file, indent=2, ensure_ascii=False)
        file.write("\n")


def normalize_course_id(value: Any) -> str:
    if not isinstance(value, str):
        return ""

    normalized = re.sub(r"\s+", " ", value.strip().upper())
    if re.fullmatch(r"[A-Z]{2,5}_\d{4}[A-Z]?", normalized):
        subject, number = normalized.split("_", 1)
    else:
        match = COURSE_CODE_RE.search(normalized)
        if not match:
            return ""
        subject = match.group("subject")
        number = match.group("number")

    if number.endswith("E"):
        number = number[:-1]
    return f"{subject}_{number}"


def build_course_id_lookup(courses: list[dict[str, Any]]) -> set[str]:
    course_ids = set()
    for course in courses:
        course_ids.add(normalize_course_id(course.get("course_code")))
        for alias in course.get("aliases") or []:
            course_ids.add(normalize_course_id(alias))
    return {course_id for course_id in course_ids if course_id}


def iter_course_requirements(rule: dict[str, Any]):
    for group in rule.get("groups") or []:
        for requirement in group.get("requirements") or []:
            if requirement.get("type") == "course":
                yield group, requirement


def build_prerequisite_edges(
    courses_path: Path = DEFAULT_COURSES_PATH,
    rules_path: Path = DEFAULT_RULES_PATH,
) -> dict[str, Any]:
    courses = load_json(courses_path)
    rules = load_json(rules_path)
    course_lookup = build_course_id_lookup(courses)

    edges: list[dict[str, Any]] = []
    unresolved: list[dict[str, Any]] = []
    self_referential_edges: list[dict[str, Any]] = []
    seen_edges = set()

    for rule in rules:
        unlocked_course_id = normalize_course_id(rule.get("course_id"))
        if not unlocked_course_id:
            continue
        if rule.get("rule_type") in {"none", "non_course_requirement"}:
            continue

        for group, requirement in iter_course_requirements(rule):
            prerequisite_course_id = normalize_course_id(requirement.get("course_id"))
            if not prerequisite_course_id:
                continue

            is_resolved = prerequisite_course_id in course_lookup
            is_self_referential = prerequisite_course_id == unlocked_course_id
            edge_key = (
                prerequisite_course_id,
                unlocked_course_id,
                group.get("group_id"),
                requirement.get("raw_condition_text"),
            )

            edge = {
                "edge_id": f"{prerequisite_course_id}_to_{unlocked_course_id}_{len(edges) + 1}",
                "prerequisite_course_id": prerequisite_course_id,
                "unlocked_course_id": unlocked_course_id,
                "requirement_group_id": group.get("group_id"),
                "course_rule_type": rule.get("rule_type"),
                "group_rule_type": group.get("rule_type"),
                "logic_operator": group.get("operator"),
                "minimum_grade": requirement.get("minimum_grade"),
                "raw_condition_text": requirement.get("raw_condition_text"),
                "raw_text": group.get("raw_text") or rule.get("raw_text"),
                "parse_status": rule.get("parse_status"),
                "is_resolved": is_resolved,
                "is_self_referential": is_self_referential,
            }

            if edge_key not in seen_edges:
                edges.append(edge)
                seen_edges.add(edge_key)

            if not is_resolved:
                unresolved.append(
                    {
                        "course_id": unlocked_course_id,
                        "prerequisite_course_id": prerequisite_course_id,
                        "requirement_group_id": group.get("group_id"),
                        "raw_condition_text": requirement.get("raw_condition_text"),
                        "raw_text": group.get("raw_text") or rule.get("raw_text"),
                    }
                )

            if is_self_referential:
                self_referential_edges.append(edge)

    edge_counts_by_status = Counter(edge["parse_status"] for edge in edges)
    edge_counts_by_operator = Counter(edge["logic_operator"] or "SINGLE" for edge in edges)

    return {
        "metadata": {
            "courses_loaded": len(courses),
            "rules_loaded": len(rules),
            "edges_created": len(edges),
            "unresolved_reference_count": len(unresolved),
            "self_referential_edge_count": len(self_referential_edges),
            "edge_counts_by_parse_status": dict(sorted(edge_counts_by_status.items())),
            "edge_counts_by_logic_operator": dict(sorted(edge_counts_by_operator.items())),
            "edge_direction": "prerequisite_course_id -> unlocked_course_id",
            "source_rules_path": str(rules_path),
            "source_courses_path": str(courses_path),
        },
        "edges": edges,
        "unresolved_prerequisite_references": unresolved,
        "self_referential_edges": self_referential_edges,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Build UGA prerequisite graph edges.")
    parser.add_argument("--courses-path", type=Path, default=DEFAULT_COURSES_PATH)
    parser.add_argument("--rules-path", type=Path, default=DEFAULT_RULES_PATH)
    parser.add_argument("--output-path", type=Path, default=DEFAULT_OUTPUT_PATH)
    args = parser.parse_args()

    payload = build_prerequisite_edges(args.courses_path, args.rules_path)
    write_json(args.output_path, payload)

    print(f"Wrote {payload['metadata']['edges_created']} prerequisite edges to {args.output_path}")
    print(f"Unresolved references: {payload['metadata']['unresolved_reference_count']}")
    print(f"Self-referential edges: {payload['metadata']['self_referential_edge_count']}")


if __name__ == "__main__":
    main()
