"""Build course prerequisite rule objects from parsed UGA prerequisite artifacts."""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[3]
PREREQ_DIR = PROJECT_ROOT / "data" / "processed" / "uga" / "prerequisites"

AUDIT_PATH = PREREQ_DIR / "prerequisite_parse_audit.json"
GROUPS_PATH = PREREQ_DIR / "prerequisite_groups.json"
ITEMS_PATH = PREREQ_DIR / "prerequisite_items.json"
OUTPUT_PATH = PREREQ_DIR / "prerequisite_rules.json"

NON_COURSE_MARKERS = (
    "permission",
    "consent",
    "department",
    "departmental",
    "honors",
    "placement",
    "standing",
    "permission of",
)


def load_json(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as file:
        return json.load(file)


def write_json(path: Path, data: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as file:
        json.dump(data, file, indent=2, ensure_ascii=False)
        file.write("\n")


def rule_type_for_operator(operator: str | None) -> str:
    if operator == "OR":
        return "one_of"
    return "all_of"


def normalize_parse_status(status: str) -> str:
    if status == "needs_review":
        return "manual_review"
    return status


def is_non_course_requirement(raw_text: str, notes: list[str]) -> bool:
    searchable = f"{raw_text} {' '.join(notes)}".lower()
    return any(marker in searchable for marker in NON_COURSE_MARKERS)


def build_requirement(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "course",
        "course_id": item["prerequisite_course_id"],
        "minimum_grade": item.get("minimum_grade"),
        "raw_condition_text": item.get("raw_condition_text"),
    }


def build_group(
    group: dict[str, Any],
    items_by_group: dict[str, list[dict[str, Any]]],
) -> dict[str, Any]:
    group_items = items_by_group.get(group["requirement_group"], [])
    return {
        "group_id": group["requirement_group"],
        "rule_type": rule_type_for_operator(group.get("group_operator")),
        "operator": group.get("group_operator"),
        "requirements": [build_requirement(item) for item in group_items],
        "raw_text": group.get("raw_text"),
    }


def build_rules() -> list[dict[str, Any]]:
    audit_records = load_json(AUDIT_PATH)
    groups = load_json(GROUPS_PATH)
    items = load_json(ITEMS_PATH)

    groups_by_course: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for group in groups:
        groups_by_course[group["course_id"]].append(group)

    items_by_group: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in items:
        items_by_group[item["requirement_group"]].append(item)

    rules: list[dict[str, Any]] = []
    for audit in audit_records:
        course_id = audit["course_id"]
        raw_text = audit.get("raw_text") or ""
        notes = list(audit.get("notes") or [])
        course_groups = groups_by_course.get(course_id, [])
        parse_status = normalize_parse_status(audit["parse_status"])

        if audit["parse_status"] == "no_prerequisite":
            rules.append(
                {
                    "course_id": course_id,
                    "rule_type": "none",
                    "groups": [],
                    "raw_text": raw_text,
                    "parse_status": "no_prerequisite",
                    "notes": notes,
                }
            )
            continue

        if not course_groups:
            rule_type = (
                "non_course_requirement"
                if is_non_course_requirement(raw_text, notes)
                else "manual_review"
            )
            rules.append(
                {
                    "course_id": course_id,
                    "rule_type": rule_type,
                    "groups": [],
                    "raw_text": raw_text,
                    "parse_status": rule_type,
                    "notes": notes,
                }
            )
            continue

        parent_operator = audit.get("parent_operator")
        if parent_operator:
            rule_type = rule_type_for_operator(parent_operator)
        elif len(course_groups) == 1:
            rule_type = rule_type_for_operator(course_groups[0].get("group_operator"))
        else:
            rule_type = "all_of"

        if parse_status == "manual_review":
            rule_type = "manual_review"

        rules.append(
            {
                "course_id": course_id,
                "rule_type": rule_type,
                "operator": parent_operator,
                "groups": [build_group(group, items_by_group) for group in course_groups],
                "raw_text": raw_text,
                "parse_status": parse_status,
                "notes": notes,
            }
        )

    return rules


def main() -> None:
    rules = build_rules()
    write_json(OUTPUT_PATH, rules)

    counts: dict[str, int] = defaultdict(int)
    for rule in rules:
        counts[rule["rule_type"]] += 1

    print(f"Wrote {len(rules)} prerequisite rules to {OUTPUT_PATH}")
    print(dict(sorted(counts.items())))


if __name__ == "__main__":
    main()
