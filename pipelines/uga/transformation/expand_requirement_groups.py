"""Expand normalized UGA degree requirement groups into concrete course lists."""

from __future__ import annotations

import argparse
import json
import re
from copy import deepcopy
from pathlib import Path
from typing import Any


ROOT_DIR = Path(__file__).resolve().parents[3]
DEFAULT_COURSES_PATH = ROOT_DIR / "data" / "processed" / "uga" / "courses" / "courses_normalized.json"
DEFAULT_REQUIREMENTS_PATH = (
    ROOT_DIR
    / "data"
    / "processed"
    / "uga"
    / "degree_requirements"
    / "degree_requirements_normalized.json"
)
DEFAULT_OUTPUT_PATH = (
    ROOT_DIR
    / "data"
    / "processed"
    / "uga"
    / "degree_requirements"
    / "degree_requirements_expanded.json"
)

IN_SCOPE_SUBJECTS = {"CSCI", "MATH", "STAT"}
COURSE_CODE_RE = re.compile(
    r"^(?P<subject>[A-Z]{2,5})(?:\([A-Z()]+\))*\s+(?P<number>[0-9A-Z/\-]+)$"
)


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as file:
        return json.load(file)


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as file:
        json.dump(payload, file, indent=2, ensure_ascii=False)
        file.write("\n")


def normalize_course_code(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    return re.sub(r"\s+", " ", value.strip().upper())


def course_id_from_code(course_code: str) -> str:
    normalized = normalize_course_code(course_code)
    match = COURSE_CODE_RE.match(normalized)
    if not match:
        return ""
    number = match.group("number").split("/")[0].split("-")[0]
    if number.endswith("E"):
        number = number[:-1]
    return f"{match.group('subject')}_{number}"


def course_level(course: dict[str, Any]) -> int | None:
    match = re.search(r"\d{4}", normalize_course_code(course.get("course_number")))
    return int(match.group(0)) if match else None


def course_record(course: dict[str, Any], matched_alias: str | None = None) -> dict[str, Any]:
    return {
        "course_code": course.get("course_code"),
        "course_id": course_id_from_code(course.get("course_code", "")),
        "matched_alias": matched_alias or course.get("course_code"),
        "subject": course.get("subject"),
        "course_number": course.get("course_number"),
        "title": course.get("title"),
        "credits": course.get("credits"),
    }


def build_course_lookup(courses: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    lookup = {}
    for course in courses:
        aliases = [course.get("course_code"), *(course.get("aliases") or [])]
        for alias in aliases:
            normalized_alias = normalize_course_code(alias)
            if normalized_alias:
                lookup[normalized_alias] = course
    return lookup


def resolve_course_reference(
    course_code: str,
    course_lookup: dict[str, dict[str, Any]],
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    normalized = normalize_course_code(course_code)
    course = course_lookup.get(normalized)
    if course:
        return course_record(course, normalized), None

    return None, {
        "course_code": normalized,
        "course_id": course_id_from_code(normalized),
        "reason": "Course reference not found in normalized CSCI/MATH/STAT course list.",
    }


def explicit_excluded_aliases(requirement: dict[str, Any]) -> set[str]:
    exclusions = requirement.get("exclusions") or {}
    return {normalize_course_code(course) for course in exclusions.get("exclude_courses", [])}


def matches_filter(course: dict[str, Any], course_filter: dict[str, Any]) -> bool:
    subject = normalize_course_code(course_filter.get("subject"))
    minimum_level = course_filter.get("minimum_level")
    maximum_level = course_filter.get("maximum_level")
    course_subject = normalize_course_code(course.get("subject"))
    level = course_level(course)

    if course_subject not in IN_SCOPE_SUBJECTS:
        return False
    if subject and course_subject != subject:
        return False
    if level is None:
        return False
    if minimum_level is not None and level < int(minimum_level):
        return False
    if maximum_level is not None and level > int(maximum_level):
        return False
    return True


def expand_course_filter(
    requirement: dict[str, Any],
    courses: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    course_filter = requirement.get("course_filter")
    if not course_filter:
        return []

    excluded_aliases = explicit_excluded_aliases(requirement)
    resolved = []
    seen_codes = set()
    for course in courses:
        if not matches_filter(course, course_filter):
            continue
        aliases = {normalize_course_code(course.get("course_code")), *(normalize_course_code(alias) for alias in course.get("aliases") or [])}
        if aliases & excluded_aliases:
            continue
        course_code = normalize_course_code(course.get("course_code"))
        if course_code in seen_codes:
            continue
        seen_codes.add(course_code)
        resolved.append(course_record(course))

    return sorted(resolved, key=lambda item: item["course_code"])


def expand_requirement(
    requirement: dict[str, Any],
    courses: list[dict[str, Any]],
    course_lookup: dict[str, dict[str, Any]],
) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, Any] | None]:
    expanded = deepcopy(requirement)
    resolved_courses = []
    unresolved_courses = []

    for course_code in requirement.get("courses") or []:
        resolved, unresolved = resolve_course_reference(course_code, course_lookup)
        if resolved:
            resolved_courses.append(resolved)
        if unresolved:
            unresolved_courses.append({**unresolved, "requirement_id": requirement.get("id")})

    filter_courses = expand_course_filter(requirement, courses)
    resolved_courses.extend(filter_courses)

    seen_codes = set()
    deduped_courses = []
    for course in resolved_courses:
        course_code = normalize_course_code(course.get("course_code"))
        if course_code in seen_codes:
            continue
        seen_codes.add(course_code)
        deduped_courses.append(course)

    expanded["resolved_courses"] = deduped_courses
    expanded["expanded_course_codes"] = [course["course_code"] for course in deduped_courses]
    expanded["unresolved_courses"] = unresolved_courses
    expanded["empty_filter"] = bool(requirement.get("course_filter")) and not filter_courses

    empty_filter = None
    if expanded["empty_filter"]:
        empty_filter = {
            "requirement_id": requirement.get("id"),
            "course_filter": requirement.get("course_filter"),
        }

    return expanded, unresolved_courses, empty_filter


def expand_degree_requirements(
    courses_path: Path = DEFAULT_COURSES_PATH,
    requirements_path: Path = DEFAULT_REQUIREMENTS_PATH,
) -> dict[str, Any]:
    courses = load_json(courses_path)
    requirements_payload = load_json(requirements_path)
    requirements = requirements_payload.get("requirements", [])
    course_lookup = build_course_lookup(courses)

    expanded_requirements = []
    unresolved_courses = []
    empty_filters = []

    for requirement in requirements:
        expanded, unresolved, empty_filter = expand_requirement(requirement, courses, course_lookup)
        expanded_requirements.append(expanded)
        unresolved_courses.extend(unresolved)
        if empty_filter:
            empty_filters.append(empty_filter)

    return {
        "program": requirements_payload.get("program", {}),
        "metadata": {
            "courses_loaded": len(courses),
            "requirements_loaded": len(requirements),
            "requirements_expanded": len(expanded_requirements),
            "empty_filter_count": len(empty_filters),
            "unresolved_course_count": len(unresolved_courses),
            "in_scope_subjects": sorted(IN_SCOPE_SUBJECTS),
            "source_courses_path": str(courses_path),
            "source_requirements_path": str(requirements_path),
        },
        "requirements": expanded_requirements,
        "empty_filters": empty_filters,
        "unresolved_courses": unresolved_courses,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Expand UGA degree requirement groups.")
    parser.add_argument("--courses-path", type=Path, default=DEFAULT_COURSES_PATH)
    parser.add_argument("--requirements-path", type=Path, default=DEFAULT_REQUIREMENTS_PATH)
    parser.add_argument("--output-path", type=Path, default=DEFAULT_OUTPUT_PATH)
    args = parser.parse_args()

    payload = expand_degree_requirements(args.courses_path, args.requirements_path)
    write_json(args.output_path, payload)

    print(f"Wrote {payload['metadata']['requirements_expanded']} expanded requirements to {args.output_path}")
    print(f"Empty filters: {payload['metadata']['empty_filter_count']}")
    print(f"Unresolved courses: {payload['metadata']['unresolved_course_count']}")


if __name__ == "__main__":
    main()
