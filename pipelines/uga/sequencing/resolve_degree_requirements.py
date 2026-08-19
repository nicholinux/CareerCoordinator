"""Resolve expanded UGA degree requirements into a concrete selected degree plan."""

from __future__ import annotations

import argparse
import json
import re
from collections import defaultdict
from pathlib import Path
from typing import Any


ROOT_DIR = Path(__file__).resolve().parents[3]
DEFAULT_REQUIREMENTS_PATH = (
    ROOT_DIR
    / "data"
    / "processed"
    / "uga"
    / "degree_requirements"
    / "degree_requirements_expanded.json"
)
DEFAULT_GRAPH_PATH = ROOT_DIR / "data" / "processed" / "uga" / "curriculum_graph" / "curriculum_graph.json"
DEFAULT_OUTPUT_PATH = ROOT_DIR / "data" / "processed" / "uga" / "curriculum" / "selected_degree_plan.json"

COURSE_CODE_RE = re.compile(r"^(?P<subject>[A-Z]{2,5})(?:\([A-Z()]+\))*\s+(?P<number>[0-9A-Z/\-]+)$")


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


def course_id_from_code(value: Any) -> str:
    normalized = normalize_course_code(value)
    if re.fullmatch(r"[A-Z]{2,5}_\d{4}[A-Z]?", normalized):
        subject, number = normalized.split("_", 1)
    else:
        match = COURSE_CODE_RE.match(normalized)
        if not match:
            return ""
        subject = match.group("subject")
        number = match.group("number").split("/")[0].split("-")[0]

    if number.endswith("E"):
        number = number[:-1]
    return f"{subject}_{number}"


def parse_course_list(values: list[str] | None) -> set[str]:
    course_ids = set()
    for value in values or []:
        for part in value.split(","):
            course_id = course_id_from_code(part)
            if course_id:
                course_ids.add(course_id)
    return course_ids


def load_completed_courses(path: Path | None) -> set[str]:
    if not path:
        return set()
    payload = load_json(path)
    if isinstance(payload, dict):
        values = payload.get("completed_courses") or []
    elif isinstance(payload, list):
        values = payload
    else:
        values = []
    return parse_course_list([str(value) for value in values])


def dependency_depths(graph: dict[str, Any]) -> dict[str, int]:
    depths = {}
    for index, course_id in enumerate(graph.get("topological_course_order") or []):
        depths.setdefault(course_id, index)

    # Prefer compact dependency levels when available from generated plan output later,
    # but topological index still gives stable ordering before that exists.
    return depths


def edges_by_course(graph: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for edge in graph.get("edges") or []:
        grouped[edge["unlocked_course_id"]].append(edge)
    return grouped


def prerequisite_groups(edges: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[str, dict[str, Any]] = {}
    for edge in edges:
        group_id = edge.get("requirement_group_id") or f"{edge['unlocked_course_id']}_implicit"
        group = groups.setdefault(
            group_id,
            {
                "group_id": group_id,
                "rule_type": edge.get("group_rule_type") or "all_of",
                "operator": edge.get("logic_operator"),
                "course_ids": [],
            },
        )
        group["course_ids"].append(edge["prerequisite_course_id"])
    return list(groups.values())


def unmet_prerequisite_groups(
    course_id: str,
    grouped_edges: dict[str, list[dict[str, Any]]],
    satisfied_course_ids: set[str],
) -> list[dict[str, Any]]:
    unmet = []
    for group in prerequisite_groups(grouped_edges.get(course_id, [])):
        course_ids = group["course_ids"]
        is_one_of = group.get("rule_type") == "one_of" or group.get("operator") == "OR"
        if is_one_of:
            if not any(prereq in satisfied_course_ids for prereq in course_ids):
                unmet.append({**group, "missing_course_ids": course_ids})
        else:
            missing = [prereq for prereq in course_ids if prereq not in satisfied_course_ids]
            if missing:
                unmet.append({**group, "missing_course_ids": missing})
    return unmet


def course_summary(course_id: str, graph: dict[str, Any]) -> dict[str, Any]:
    node = graph["nodes"].get(course_id, {})
    return {
        "course_id": course_id,
        "course_code": node.get("course_code"),
        "title": node.get("title"),
        "credits": node.get("credits") or 0,
        "requirement_group_ids": node.get("requirement_group_ids") or [],
    }


def excluded_course_ids(requirement: dict[str, Any]) -> set[str]:
    exclusions = requirement.get("exclusions") or {}
    return {course_id_from_code(course_code) for course_code in exclusions.get("exclude_courses", [])}


def courses_used_by_requirement_ids(
    requirement: dict[str, Any],
    selected_by_requirement: dict[str, list[dict[str, Any]]],
) -> set[str]:
    exclusions = requirement.get("exclusions") or {}
    excluded_requirement_ids = exclusions.get("exclude_courses_used_by_requirement_ids") or []
    used = set()
    for requirement_id in excluded_requirement_ids:
        for course in selected_by_requirement.get(requirement_id, []):
            used.add(course["course_id"])
    return used


def candidate_score(
    course_id: str,
    graph: dict[str, Any],
    grouped_edges: dict[str, list[dict[str, Any]]],
    satisfied_course_ids: set[str],
    depths: dict[str, int],
) -> tuple[int, int, int, str]:
    unmet_groups = unmet_prerequisite_groups(course_id, grouped_edges, satisfied_course_ids)
    unmet_count = sum(len(group["missing_course_ids"]) for group in unmet_groups)
    depth = depths.get(course_id, 9999)
    level = graph["nodes"].get(course_id, {}).get("level") or 9999
    return (unmet_count, depth, level, course_id)


def resolved_course_ids(requirement: dict[str, Any]) -> list[str]:
    ids = []
    for course in requirement.get("resolved_courses") or []:
        course_id = course.get("course_id") or course_id_from_code(course.get("course_code"))
        if course_id:
            ids.append(course_id)
    return ids


def select_course(
    course_id: str,
    requirement: dict[str, Any],
    graph: dict[str, Any],
    grouped_edges: dict[str, list[dict[str, Any]]],
    satisfied_course_ids: set[str],
    reason: str,
) -> dict[str, Any]:
    summary = course_summary(course_id, graph)
    unmet_groups = unmet_prerequisite_groups(course_id, grouped_edges, satisfied_course_ids)
    return {
        **summary,
        "requirement_id": requirement.get("id"),
        "requirement_name": requirement.get("name"),
        "selection_reason": reason,
        "unmet_prerequisite_count_at_selection": sum(len(group["missing_course_ids"]) for group in unmet_groups),
        "unmet_prerequisite_groups_at_selection": unmet_groups,
    }


def select_best_candidate(
    candidate_ids: list[str],
    graph: dict[str, Any],
    grouped_edges: dict[str, list[dict[str, Any]]],
    satisfied_course_ids: set[str],
    depths: dict[str, int],
) -> str | None:
    available = [course_id for course_id in candidate_ids if course_id in graph["nodes"]]
    if not available:
        return None
    return min(
        available,
        key=lambda course_id: candidate_score(course_id, graph, grouped_edges, satisfied_course_ids, depths),
    )


def resolve_degree_requirements(
    requirements_path: Path = DEFAULT_REQUIREMENTS_PATH,
    graph_path: Path = DEFAULT_GRAPH_PATH,
    completed_course_ids: set[str] | None = None,
) -> dict[str, Any]:
    requirements_payload = load_json(requirements_path)
    graph = load_json(graph_path)
    requirements = requirements_payload.get("requirements") or []
    completed_course_ids = {course_id for course_id in completed_course_ids or set() if course_id in graph["nodes"]}

    grouped_edges = edges_by_course(graph)
    depths = dependency_depths(graph)
    selected_by_requirement: dict[str, list[dict[str, Any]]] = {}
    unselected_by_requirement: dict[str, list[dict[str, Any]]] = {}
    selected_unique_ids: set[str] = set()
    satisfied_course_ids = set(completed_course_ids)

    requirement_results = []
    for requirement in requirements:
        requirement_id = requirement.get("id")
        requirement_type = requirement.get("type")
        candidate_ids = resolved_course_ids(requirement)
        overlap_allowed = bool(requirement.get("overlap_allowed", False))
        excluded_ids = excluded_course_ids(requirement) | courses_used_by_requirement_ids(
            requirement, selected_by_requirement
        )
        if not overlap_allowed:
            excluded_ids |= selected_unique_ids

        available_candidate_ids = [
            course_id for course_id in candidate_ids if course_id in graph["nodes"] and course_id not in excluded_ids
        ]
        selected = []

        if requirement_type == "all_of":
            for course_id in available_candidate_ids:
                selected_course = select_course(
                    course_id,
                    requirement,
                    graph,
                    grouped_edges,
                    satisfied_course_ids,
                    "Required by all_of requirement group.",
                )
                selected.append(selected_course)
                selected_unique_ids.add(course_id)
                satisfied_course_ids.add(course_id)
        elif requirement_type == "one_of":
            course_id = select_best_candidate(available_candidate_ids, graph, grouped_edges, satisfied_course_ids, depths)
            if course_id:
                selected_course = select_course(
                    course_id,
                    requirement,
                    graph,
                    grouped_edges,
                    satisfied_course_ids,
                    "Selected from one_of options because it had the fewest unmet prerequisites and lowest dependency depth.",
                )
                selected.append(selected_course)
                if not overlap_allowed:
                    selected_unique_ids.add(course_id)
                satisfied_course_ids.add(course_id)
        elif requirement_type == "minimum_credits":
            selected_credits = 0
            remaining_candidates = list(available_candidate_ids)
            while selected_credits < int(requirement.get("minimum_credits") or 0) and remaining_candidates:
                course_id = select_best_candidate(remaining_candidates, graph, grouped_edges, satisfied_course_ids, depths)
                if not course_id:
                    break
                selected_course = select_course(
                    course_id,
                    requirement,
                    graph,
                    grouped_edges,
                    satisfied_course_ids,
                    "Selected toward minimum_credits using fewest unmet prerequisites and lowest dependency depth.",
                )
                selected.append(selected_course)
                selected_credits += int(selected_course.get("credits") or 0)
                selected_unique_ids.add(course_id)
                satisfied_course_ids.add(course_id)
                remaining_candidates.remove(course_id)
        elif requirement_type == "note":
            selected = []

        selected_by_requirement[requirement_id] = selected
        selected_ids = {course["course_id"] for course in selected}
        unselected = [
            {
                **course_summary(course_id, graph),
                "reason": "Not selected for this requirement.",
            }
            for course_id in candidate_ids
            if course_id in graph["nodes"] and course_id not in selected_ids
        ]
        unselected_by_requirement[requirement_id] = unselected

        selected_credits = sum(int(course.get("credits") or 0) for course in selected)
        minimum_credits = requirement.get("minimum_credits")
        is_satisfied = bool(selected)
        if requirement_type == "all_of":
            is_satisfied = len(selected) == len(available_candidate_ids)
        elif requirement_type == "one_of":
            is_satisfied = len(selected) == 1
        elif requirement_type == "minimum_credits":
            is_satisfied = selected_credits >= int(minimum_credits or 0)
        elif requirement_type == "note":
            is_satisfied = True

        requirement_results.append(
            {
                "requirement_id": requirement_id,
                "requirement_name": requirement.get("name"),
                "requirement_type": requirement_type,
                "minimum_credits": minimum_credits,
                "overlap_allowed": overlap_allowed,
                "is_satisfied": is_satisfied,
                "selected_credits": selected_credits,
                "selected_courses": selected,
                "unselected_alternatives": unselected,
                "excluded_course_ids": sorted(excluded_ids),
                "notes": requirement.get("notes") or [],
            }
        )

    all_selected = [course for courses in selected_by_requirement.values() for course in courses]
    unique_selected_ids = sorted({course["course_id"] for course in all_selected})

    return {
        "program": requirements_payload.get("program", {}),
        "metadata": {
            "requirements_loaded": len(requirements),
            "requirements_satisfied": sum(1 for item in requirement_results if item["is_satisfied"]),
            "requirements_unsatisfied": sum(1 for item in requirement_results if not item["is_satisfied"]),
            "selected_course_count": len(all_selected),
            "unique_selected_course_count": len(unique_selected_ids),
            "completed_course_count": len(completed_course_ids),
            "source_requirements_path": str(requirements_path),
            "source_graph_path": str(graph_path),
        },
        "completed_courses": [course_summary(course_id, graph) for course_id in sorted(completed_course_ids)],
        "requirements": requirement_results,
        "selected_courses": [course_summary(course_id, graph) for course_id in unique_selected_ids],
        "unselected_alternatives_by_requirement": unselected_by_requirement,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Resolve UGA degree requirements into a selected course plan.")
    parser.add_argument("--requirements-path", type=Path, default=DEFAULT_REQUIREMENTS_PATH)
    parser.add_argument("--graph-path", type=Path, default=DEFAULT_GRAPH_PATH)
    parser.add_argument("--output-path", type=Path, default=DEFAULT_OUTPUT_PATH)
    parser.add_argument("--completed-courses", nargs="*", default=None)
    parser.add_argument("--completed-courses-path", type=Path, default=None)
    args = parser.parse_args()

    completed_course_ids = parse_course_list(args.completed_courses)
    completed_course_ids.update(load_completed_courses(args.completed_courses_path))

    payload = resolve_degree_requirements(args.requirements_path, args.graph_path, completed_course_ids)
    write_json(args.output_path, payload)

    print(f"Wrote selected degree plan to {args.output_path}")
    print(f"Requirements satisfied: {payload['metadata']['requirements_satisfied']}")
    print(f"Requirements unsatisfied: {payload['metadata']['requirements_unsatisfied']}")
    print(f"Unique selected courses: {payload['metadata']['unique_selected_course_count']}")


if __name__ == "__main__":
    main()
