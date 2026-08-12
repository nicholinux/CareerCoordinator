"""Build a curriculum graph from normalized UGA course and requirement data."""

from __future__ import annotations

import argparse
import json
import re
from collections import defaultdict, deque
from pathlib import Path
from typing import Any


ROOT_DIR = Path(__file__).resolve().parents[3]
DEFAULT_COURSES_PATH = ROOT_DIR / "data" / "processed" / "uga" / "courses" / "courses_normalized.json"
DEFAULT_RULES_PATH = ROOT_DIR / "data" / "processed" / "uga" / "prerequisites" / "prerequisite_rules.json"
DEFAULT_EDGES_PATH = ROOT_DIR / "data" / "processed" / "uga" / "prerequisites" / "prerequisite_edges.json"
DEFAULT_REQUIREMENTS_PATH = (
    ROOT_DIR
    / "data"
    / "processed"
    / "uga"
    / "degree_requirements"
    / "degree_requirements_expanded.json"
)
DEFAULT_OUTPUT_PATH = ROOT_DIR / "data" / "processed" / "uga" / "curriculum_graph" / "curriculum_graph.json"

COURSE_CODE_RE = re.compile(r"^(?P<subject>[A-Z]{2,5})(?:\([A-Z()]+\))*\s+(?P<number>[0-9A-Z/\-]+)$")
IN_SCOPE_SUBJECTS = {"CSCI", "MATH", "STAT"}


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


def course_id_from_code(course_code: Any) -> str:
    normalized = normalize_course_code(course_code)
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


def course_level(course_number: Any) -> int | None:
    match = re.search(r"\d{4}", normalize_course_code(course_number))
    return int(match.group(0)) if match else None


def requirement_course_memberships(requirements: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    memberships: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for requirement in requirements:
        for course in requirement.get("resolved_courses") or []:
            course_id = course.get("course_id") or course_id_from_code(course.get("course_code"))
            if not course_id:
                continue
            memberships[course_id].append(
                {
                    "requirement_id": requirement.get("id"),
                    "requirement_name": requirement.get("name"),
                    "requirement_type": requirement.get("type"),
                    "minimum_credits": requirement.get("minimum_credits"),
                    "overlap_allowed": bool(requirement.get("overlap_allowed", False)),
                }
            )
    return memberships


def required_course_ids(requirements: list[dict[str, Any]]) -> set[str]:
    required_ids = set()
    for requirement in requirements:
        if requirement.get("type") != "all_of":
            continue
        for course in requirement.get("resolved_courses") or []:
            course_id = course.get("course_id") or course_id_from_code(course.get("course_code"))
            if course_id:
                required_ids.add(course_id)
    return required_ids


def elective_candidate_ids(requirements: list[dict[str, Any]]) -> set[str]:
    candidate_ids = set()
    for requirement in requirements:
        if requirement.get("type") not in {"one_of", "minimum_credits"}:
            continue
        for course in requirement.get("resolved_courses") or []:
            course_id = course.get("course_id") or course_id_from_code(course.get("course_code"))
            if course_id:
                candidate_ids.add(course_id)
    return candidate_ids


def prerequisite_rule_lookup(rules: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {rule["course_id"]: rule for rule in rules if rule.get("course_id")}


def build_nodes(
    courses: list[dict[str, Any]],
    requirements: list[dict[str, Any]],
    rules: list[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    memberships = requirement_course_memberships(requirements)
    required_ids = required_course_ids(requirements)
    elective_ids = elective_candidate_ids(requirements)
    rules_by_course = prerequisite_rule_lookup(rules)

    nodes = {}
    for course in courses:
        if normalize_course_code(course.get("subject")) not in IN_SCOPE_SUBJECTS:
            continue
        course_id = course_id_from_code(course.get("course_code"))
        if not course_id:
            continue
        requirement_memberships = memberships.get(course_id, [])
        nodes[course_id] = {
            "course_id": course_id,
            "course_code": course.get("course_code"),
            "subject": course.get("subject"),
            "course_number": course.get("course_number"),
            "level": course_level(course.get("course_number")),
            "title": course.get("title"),
            "credits": course.get("credits"),
            "credit_hours_text": course.get("credit_hours_text"),
            "description": course.get("description"),
            "prerequisites": course.get("prerequisites"),
            "aliases": course.get("aliases") or [],
            "source_file": course.get("source_file"),
            "source_url": course.get("source_url"),
            "requirement_groups": requirement_memberships,
            "requirement_group_ids": [item["requirement_id"] for item in requirement_memberships],
            "is_required": course_id in required_ids,
            "is_elective_candidate": course_id in elective_ids,
            "prerequisite_rule_type": (rules_by_course.get(course_id) or {}).get("rule_type"),
            "prerequisite_parse_status": (rules_by_course.get(course_id) or {}).get("parse_status"),
        }
    return nodes


def filter_edges(edges_payload: dict[str, Any], nodes: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    node_ids = set(nodes)
    graph_edges = []
    for edge in edges_payload.get("edges") or []:
        if edge.get("prerequisite_course_id") not in node_ids:
            continue
        if edge.get("unlocked_course_id") not in node_ids:
            continue
        graph_edges.append(edge)
    return graph_edges


def attach_adjacency(nodes: dict[str, dict[str, Any]], edges: list[dict[str, Any]]) -> None:
    prerequisites_by_course: dict[str, list[str]] = defaultdict(list)
    unlocks_by_course: dict[str, list[str]] = defaultdict(list)

    for edge in edges:
        prerequisite = edge["prerequisite_course_id"]
        unlocked = edge["unlocked_course_id"]
        prerequisites_by_course[unlocked].append(prerequisite)
        unlocks_by_course[prerequisite].append(unlocked)

    for course_id, node in nodes.items():
        node["prerequisite_course_ids"] = sorted(set(prerequisites_by_course.get(course_id, [])))
        node["unlocks_course_ids"] = sorted(set(unlocks_by_course.get(course_id, [])))
        node["prerequisite_count"] = len(node["prerequisite_course_ids"])
        node["unlocks_count"] = len(node["unlocks_course_ids"])


def detect_cycles(nodes: dict[str, dict[str, Any]], edges: list[dict[str, Any]]) -> list[list[str]]:
    adjacency: dict[str, list[str]] = defaultdict(list)
    for edge in edges:
        adjacency[edge["prerequisite_course_id"]].append(edge["unlocked_course_id"])

    visited: set[str] = set()
    active: set[str] = set()
    stack: list[str] = []
    cycles: list[list[str]] = []
    seen_cycles: set[tuple[str, ...]] = set()

    def visit(course_id: str) -> None:
        visited.add(course_id)
        active.add(course_id)
        stack.append(course_id)

        for neighbor in adjacency.get(course_id, []):
            if neighbor not in visited:
                visit(neighbor)
            elif neighbor in active:
                start = stack.index(neighbor)
                cycle = stack[start:] + [neighbor]
                canonical = tuple(sorted(set(cycle)))
                if canonical not in seen_cycles:
                    seen_cycles.add(canonical)
                    cycles.append(cycle)

        stack.pop()
        active.remove(course_id)

    for course_id in nodes:
        if course_id not in visited:
            visit(course_id)

    return cycles


def topological_course_order(nodes: dict[str, dict[str, Any]], edges: list[dict[str, Any]]) -> list[str]:
    in_degree = {course_id: 0 for course_id in nodes}
    adjacency: dict[str, list[str]] = defaultdict(list)

    for edge in edges:
        prerequisite = edge["prerequisite_course_id"]
        unlocked = edge["unlocked_course_id"]
        adjacency[prerequisite].append(unlocked)
        in_degree[unlocked] += 1

    queue = deque(sorted(course_id for course_id, degree in in_degree.items() if degree == 0))
    ordered = []
    while queue:
        course_id = queue.popleft()
        ordered.append(course_id)
        for unlocked in sorted(adjacency.get(course_id, [])):
            in_degree[unlocked] -= 1
            if in_degree[unlocked] == 0:
                queue.append(unlocked)

    return ordered


def requirement_group_metadata(requirements: list[dict[str, Any]]) -> list[dict[str, Any]]:
    metadata = []
    for requirement in requirements:
        metadata.append(
            {
                "id": requirement.get("id"),
                "name": requirement.get("name"),
                "type": requirement.get("type"),
                "minimum_credits": requirement.get("minimum_credits"),
                "overlap_allowed": bool(requirement.get("overlap_allowed", False)),
                "expanded_course_codes": requirement.get("expanded_course_codes") or [],
                "course_count": len(requirement.get("resolved_courses") or []),
                "exclusions": requirement.get("exclusions"),
                "notes": requirement.get("notes") or [],
                "empty_filter": bool(requirement.get("empty_filter", False)),
                "unresolved_courses": requirement.get("unresolved_courses") or [],
            }
        )
    return metadata


def build_curriculum_graph(
    courses_path: Path = DEFAULT_COURSES_PATH,
    rules_path: Path = DEFAULT_RULES_PATH,
    edges_path: Path = DEFAULT_EDGES_PATH,
    requirements_path: Path = DEFAULT_REQUIREMENTS_PATH,
) -> dict[str, Any]:
    courses = load_json(courses_path)
    rules = load_json(rules_path)
    edges_payload = load_json(edges_path)
    requirements_payload = load_json(requirements_path)
    requirements = requirements_payload.get("requirements", [])
    skipped_out_of_scope_courses = [
        course.get("course_code")
        for course in courses
        if normalize_course_code(course.get("subject")) not in IN_SCOPE_SUBJECTS
    ]

    nodes = build_nodes(courses, requirements, rules)
    edges = filter_edges(edges_payload, nodes)
    attach_adjacency(nodes, edges)

    cycles = detect_cycles(nodes, edges)
    isolated_courses = sorted(
        course_id
        for course_id, node in nodes.items()
        if node["prerequisite_count"] == 0 and node["unlocks_count"] == 0
    )

    return {
        "program": requirements_payload.get("program", {}),
        "metadata": {
            "course_count": len(nodes),
            "source_course_count": len(courses),
            "skipped_out_of_scope_course_count": len(skipped_out_of_scope_courses),
            "edge_count": len(edges),
            "requirement_group_count": len(requirements),
            "required_course_count": sum(1 for node in nodes.values() if node["is_required"]),
            "elective_candidate_count": sum(1 for node in nodes.values() if node["is_elective_candidate"]),
            "cycle_count": len(cycles),
            "isolated_course_count": len(isolated_courses),
            "unresolved_prerequisite_reference_count": len(edges_payload.get("unresolved_prerequisite_references") or []),
            "source_courses_path": str(courses_path),
            "source_rules_path": str(rules_path),
            "source_edges_path": str(edges_path),
            "source_requirements_path": str(requirements_path),
            "in_scope_subjects": sorted(IN_SCOPE_SUBJECTS),
        },
        "nodes": nodes,
        "edges": edges,
        "requirement_groups": requirement_group_metadata(requirements),
        "cycles": cycles,
        "isolated_courses": isolated_courses,
        "unresolved_prerequisite_references": edges_payload.get("unresolved_prerequisite_references") or [],
        "skipped_out_of_scope_courses": skipped_out_of_scope_courses,
        "topological_course_order": topological_course_order(nodes, edges) if not cycles else [],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Build UGA curriculum graph JSON.")
    parser.add_argument("--courses-path", type=Path, default=DEFAULT_COURSES_PATH)
    parser.add_argument("--rules-path", type=Path, default=DEFAULT_RULES_PATH)
    parser.add_argument("--edges-path", type=Path, default=DEFAULT_EDGES_PATH)
    parser.add_argument("--requirements-path", type=Path, default=DEFAULT_REQUIREMENTS_PATH)
    parser.add_argument("--output-path", type=Path, default=DEFAULT_OUTPUT_PATH)
    args = parser.parse_args()

    graph = build_curriculum_graph(args.courses_path, args.rules_path, args.edges_path, args.requirements_path)
    write_json(args.output_path, graph)

    print(f"Wrote curriculum graph to {args.output_path}")
    print(f"Courses: {graph['metadata']['course_count']}")
    print(f"Edges: {graph['metadata']['edge_count']}")
    print(f"Cycles: {graph['metadata']['cycle_count']}")
    print(f"Isolated courses: {graph['metadata']['isolated_course_count']}")


if __name__ == "__main__":
    main()
