import argparse
import json
from pathlib import Path

from prerequisite_parser import normalize_course_id, parse_prerequisites
from validators import validate_prerequisite_outputs


ROOT_DIR = Path(__file__).resolve().parents[3]
DEFAULT_RAW_DIR = ROOT_DIR / "data" / "raw" / "uga"
DEFAULT_OUTPUT_DIR = ROOT_DIR / "data" / "processed" / "uga" / "prerequisites"


def load_course_records(raw_dir: Path) -> list[dict]:
    courses = []
    for path in sorted(raw_dir.glob("*.json")):
        with path.open(encoding="utf-8") as file:
            payload = json.load(file)

        if isinstance(payload, dict) and isinstance(payload.get("courses"), list):
            courses.extend(payload["courses"])
        elif isinstance(payload, list):
            courses.extend(payload)

    return courses


def write_json(path: Path, records):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as file:
        json.dump(records, file, indent=2, ensure_ascii=False)
        file.write("\n")


def transform_prerequisites(raw_dir: Path = DEFAULT_RAW_DIR, output_dir: Path = DEFAULT_OUTPUT_DIR):
    courses = load_course_records(raw_dir)
    if not courses:
        raise ValueError(f"No course records found in {raw_dir}")

    groups = []
    items = []
    audit = []
    course_ids = []

    for course in courses:
        course_id = normalize_course_id(course.get("course_number", ""))
        if not course_id:
            continue

        course_ids.append(course_id)
        parsed = parse_prerequisites(course)
        groups.extend(parsed["groups"])
        items.extend(parsed["items"])
        audit.append(parsed["audit"])

    course_id_set = set(course_ids)
    for item in items:
        item["is_resolved"] = item["prerequisite_course_id"] in course_id_set

    validation_errors = validate_prerequisite_outputs(course_ids, groups, items, audit)
    if validation_errors:
        joined_errors = "\n".join(f"- {error}" for error in validation_errors)
        raise ValueError(f"Prerequisite validation failed:\n{joined_errors}")

    write_json(output_dir / "prerequisite_groups.json", groups)
    write_json(output_dir / "prerequisite_items.json", items)
    write_json(output_dir / "prerequisite_parse_audit.json", audit)

    return {
        "courses_processed": len(course_ids),
        "groups_created": len(groups),
        "items_created": len(items),
        "audit_records": len(audit),
        "output_dir": str(output_dir),
    }


def main():
    parser = argparse.ArgumentParser(description="Transform UGA raw catalog prerequisites.")
    parser.add_argument("--raw-dir", type=Path, default=DEFAULT_RAW_DIR)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    args = parser.parse_args()

    summary = transform_prerequisites(args.raw_dir, args.output_dir)
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
