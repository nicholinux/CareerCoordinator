"""Generate a basic prerequisite-aware course order from the UGA curriculum graph."""

from __future__ import annotations

import argparse
import json
import re
from collections import defaultdict
from pathlib import Path
from typing import Any


ROOT_DIR = Path(__file__).resolve().parents[3]
DEFAULT_GRAPH_PATH = ROOT_DIR / "data" / "processed" / "uga" / "curriculum_graph" / "curriculum_graph.json"
DEFAULT_OUTPUT_PATH = ROOT_DIR / "data" / "processed" / "uga" / "curriculum" / "recommended_course_order.json"

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


def parse_course_list(values: list[str] | None) -> list[str]:
    if not values:
        return []
    course_ids = []
    for value in values:
        for part in value.split(","):
            course_id = course_id_from_code(part)
            if course_id:
                course_ids.append(course_id)
    return course_ids


def load_course_list_file(path: Path | None, key: str) -> list[str]:
    if not path:
        return []
    payload = load_json(path)
    if isinstance(payload, dict):
        values = payload.get(key) or payload.get("courses") or []
    elif isinstance(payload, list):
        values = payload
    else:
        values = []
    return parse_course_list([str(value) for value in values])


def default_target_course_ids(nodes: dict[str, dict[str, Any]]) -> set[str]:
    return {
        course_id
        for course_id, node in nodes.items()
        if node.get("is_required") or node.get("is_elective_candidate")
    }


def build_edges_by_course(edges: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    edges_by_course: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for edge in edges:
        edges_by_course[edge["unlocked_course_id"]].append(edge)
    return edges_by_course


def prerequisite_closure(targets: set[str], edges_by_course: dict[str, list[dict[str, Any]]]) -> set[str]:
    closure = set(targets)
    stack = list(targets)
    while stack:
        course_id = stack.pop()
        for edge in edges_by_course.get(course_id, []):
            prerequisite_id = edge["prerequisite_course_id"]
            if prerequisite_id not in closure:
                closure.add(prerequisite_id)
                stack.append(prerequisite_id)
    return closure


def group_prerequisites(edges: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[str, dict[str, Any]] = {}
    for edge in edges:
        group_id = edge.get("requirement_group_id") or f"{edge['unlocked_course_id']}_implicit"
        group = groups.setdefault(
            group_id,
            {
                "group_id": group_id,
                "rule_type": edge.get("group_rule_type") or "all_of",
                "operator": edge.get("logic_operator"),
                "requirements": [],
                "raw_text": edge.get("raw_text"),
            },
        )
        group["requirements"].append(
            {
                "course_id": edge["prerequisite_course_id"],
                "minimum_grade": edge.get("minimum_grade"),
                "raw_condition_text": edge.get("raw_condition_text"),
            }
        )
    return list(groups.values())


def group_is_satisfied(group: dict[str, Any], satisfied_course_ids: set[str]) -> bool:
    requirement_ids = [item["course_id"] for item in group.get("requirements") or []]
    if not requirement_ids:
        return True
    if group.get("rule_type") == "one_of" or group.get("operator") == "OR":
        return any(course_id in satisfied_course_ids for course_id in requirement_ids)
    return all(course_id in satisfied_course_ids for course_id in requirement_ids)


def missing_for_group(group: dict[str, Any], satisfied_course_ids: set[str]) -> list[str]:
    requirement_ids = [item["course_id"] for item in group.get("requirements") or []]
    if group_is_satisfied(group, satisfied_course_ids):
        return []
    if group.get("rule_type") == "one_of" or group.get("operator") == "OR":
        return requirement_ids
    return [course_id for course_id in requirement_ids if course_id not in satisfied_course_ids]


def course_prerequisites_satisfied(
    course_id: str,
    edges_by_course: dict[str, list[dict[str, Any]]],
    satisfied_course_ids: set[str],
) -> tuple[bool, list[dict[str, Any]]]:
    groups = group_prerequisites(edges_by_course.get(course_id, []))
    missing_groups = []
    for group in groups:
        missing = missing_for_group(group, satisfied_course_ids)
        if missing:
            missing_groups.append(
                {
                    "group_id": group["group_id"],
                    "rule_type": group["rule_type"],
                    "operator": group.get("operator"),
                    "missing_course_ids": missing,
                    "raw_text": group.get("raw_text"),
                }
            )
    return not missing_groups, missing_groups


def course_summary(course_id: str, nodes: dict[str, dict[str, Any]]) -> dict[str, Any]:
    node = nodes[course_id]
    return {
        "course_id": course_id,
        "course_code": node.get("course_code"),
        "title": node.get("title"),
        "credits": node.get("credits"),
        "requirement_group_ids": node.get("requirement_group_ids") or [],
        "is_required": bool(node.get("is_required")),
        "is_elective_candidate": bool(node.get("is_elective_candidate")),
    }


def calculate_depths(
    course_ids: set[str],
    completed_course_ids: set[str],
    edges_by_course: dict[str, list[dict[str, Any]]],
) -> dict[str, int]:
    memo: dict[str, int] = {}
    visiting: set[str] = set()

    def group_depth(group: dict[str, Any]) -> int:
        requirement_ids = [
            item["course_id"]
            for item in group.get("requirements") or []
            if item["course_id"] in course_ids and item["course_id"] not in completed_course_ids
        ]
        if not requirement_ids:
            return -1
        depths = [depth_for(course_id) for course_id in requirement_ids]
        if group.get("rule_type") == "one_of" or group.get("operator") == "OR":
            return min(depths)
        return max(depths)

    def depth_for(course_id: str) -> int:
        if course_id in completed_course_ids:
            return -1
        if course_id in memo:
            return memo[course_id]
        if course_id in visiting:
            return 0

        visiting.add(course_id)
        groups = group_prerequisites(edges_by_course.get(course_id, []))
        relevant_group_depths = [group_depth(group) for group in groups]
        relevant_group_depths = [depth for depth in relevant_group_depths if depth >= 0]
        memo[course_id] = 0 if not relevant_group_depths else max(relevant_group_depths) + 1
        visiting.remove(course_id)
        return memo[course_id]

    for course_id in course_ids:
        if course_id not in completed_course_ids:
            depth_for(course_id)
    return memo


def ordered_levels(
    course_ids: set[str],
    completed_course_ids: set[str],
    nodes: dict[str, dict[str, Any]],
    edges_by_course: dict[str, list[dict[str, Any]]],
) -> list[dict[str, Any]]:
    depths = calculate_depths(course_ids, completed_course_ids, edges_by_course)
    by_depth: dict[int, list[str]] = defaultdict(list)
    for course_id, depth in depths.items():
        by_depth[depth].append(course_id)

    return [
        {
            "level": depth,
            "courses": [course_summary(course_id, nodes) for course_id in sorted(course_ids_at_depth)],
        }
        for depth, course_ids_at_depth in sorted(by_depth.items())
    ]


def relevant_unresolved_references(
    graph: dict[str, Any],
    relevant_course_ids: set[str],
) -> list[dict[str, Any]]:
    return [
        reference
        for reference in graph.get("unresolved_prerequisite_references") or []
        if reference.get("course_id") in relevant_course_ids
    ]


def generate_course_order(
    graph_path: Path = DEFAULT_GRAPH_PATH,
    target_course_ids: set[str] | None = None,
    completed_course_ids: set[str] | None = None,
) -> dict[str, Any]:
    graph = load_json(graph_path)
    nodes = graph["nodes"]
    edges = graph["edges"]
    edges_by_course = build_edges_by_course(edges)

    completed_course_ids = completed_course_ids or set()
    completed_course_ids = {course_id for course_id in completed_course_ids if course_id in nodes}

    if target_course_ids:
        target_course_ids = {course_id for course_id in target_course_ids if course_id in nodes}
    else:
        target_course_ids = default_target_course_ids(nodes)

    relevant_course_ids = prerequisite_closure(target_course_ids, edges_by_course)
    relevant_course_ids = {course_id for course_id in relevant_course_ids if course_id in nodes}
    remaining_course_ids = relevant_course_ids - completed_course_ids

    unlocked_course_ids = []
    blocked = []
    for course_id in sorted(remaining_course_ids):
        satisfied, missing_groups = course_prerequisites_satisfied(course_id, edges_by_course, completed_course_ids)
        if satisfied:
            unlocked_course_ids.append(course_id)
        else:
            blocked.append(
                {
                    **course_summary(course_id, nodes),
                    "missing_prerequisite_groups": missing_groups,
                }
            )

    return {
        "metadata": {
            "graph_path": str(graph_path),
            "target_course_count": len(target_course_ids),
            "relevant_course_count": len(relevant_course_ids),
            "completed_course_count": len(completed_course_ids),
            "remaining_course_count": len(remaining_course_ids),
            "unlocked_course_count": len(unlocked_course_ids),
            "blocked_course_count": len(blocked),
            "unresolved_prerequisite_reference_count": len(
                relevant_unresolved_references(graph, relevant_course_ids)
            ),
            "note": "Order levels are dependency levels, not semesters.",
        },
        "target_courses": [course_summary(course_id, nodes) for course_id in sorted(target_course_ids)],
        "completed_courses": [course_summary(course_id, nodes) for course_id in sorted(completed_course_ids)],
        "remaining_courses": [course_summary(course_id, nodes) for course_id in sorted(remaining_course_ids)],
        "currently_unlocked_courses": [
            course_summary(course_id, nodes) for course_id in sorted(unlocked_course_ids)
        ],
        "blocked_courses": blocked,
        "ordered_dependency_levels": ordered_levels(remaining_course_ids, completed_course_ids, nodes, edges_by_course),
        "unresolved_prerequisite_references": relevant_unresolved_references(graph, relevant_course_ids),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate a basic UGA course order from the curriculum graph.")
    parser.add_argument("--graph-path", type=Path, default=DEFAULT_GRAPH_PATH)
    parser.add_argument("--output-path", type=Path, default=DEFAULT_OUTPUT_PATH)
    parser.add_argument("--target-courses", nargs="*", default=None)
    parser.add_argument("--target-courses-path", type=Path, default=None)
    parser.add_argument("--completed-courses", nargs="*", default=None)
    parser.add_argument("--completed-courses-path", type=Path, default=None)
    args = parser.parse_args()

    target_course_ids = set(parse_course_list(args.target_courses))
    target_course_ids.update(load_course_list_file(args.target_courses_path, "target_courses"))

    completed_course_ids = set(parse_course_list(args.completed_courses))
    completed_course_ids.update(load_course_list_file(args.completed_courses_path, "completed_courses"))

    payload = generate_course_order(
        graph_path=args.graph_path,
        target_course_ids=target_course_ids or None,
        completed_course_ids=completed_course_ids,
    )
    write_json(args.output_path, payload)

    print(f"Wrote recommended course order to {args.output_path}")
    print(f"Remaining courses: {payload['metadata']['remaining_course_count']}")
    print(f"Currently unlocked courses: {payload['metadata']['unlocked_course_count']}")
    print(f"Blocked courses: {payload['metadata']['blocked_course_count']}")


if __name__ == "__main__":
    main()
