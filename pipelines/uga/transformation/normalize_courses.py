import argparse
import json
import re
from pathlib import Path
from typing import Any


ROOT_DIR = Path(__file__).resolve().parents[3]
DEFAULT_RAW_DIR = ROOT_DIR / "data" / "raw" / "uga"
DEFAULT_OUTPUT_PATH = ROOT_DIR / "data" / "processed" / "uga" / "courses" / "courses_normalized.json"

COURSE_CODE_RE = re.compile(
    r"^(?P<subject>[A-Z]{2,5})(?:\((?P<cross_subjects>[A-Z()]+)\))?\s+"
    r"(?P<number>[0-9A-Z/\-]+)$"
)
CREDIT_RE = re.compile(r"(?P<credits>\d+(?:\.\d+)?)(?:-(?P<max_credits>\d+(?:\.\d+)?))?\s+hours?", re.IGNORECASE)


def normalize_space(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    return re.sub(r"\s+", " ", value.strip())


def normalize_course_code(value: str) -> str:
    return normalize_space(value).upper()


def split_cross_subjects(value: str | None) -> list[str]:
    if not value:
        return []
    return re.findall(r"[A-Z]{2,5}", value)


def split_subject_and_number(course_code: str):
    normalized = normalize_course_code(course_code)
    match = COURSE_CODE_RE.match(normalized)
    if not match:
        parts = normalized.split(" ", 1)
        if len(parts) == 2:
            return parts[0], parts[1], []
        return "", normalized, []

    subject = match.group("subject")
    cross_subjects = split_cross_subjects(match.group("cross_subjects"))
    return subject, match.group("number"), cross_subjects


def expand_course_aliases(course_code: str) -> list[str]:
    normalized = normalize_course_code(course_code)
    match = COURSE_CODE_RE.match(normalized)
    if not match:
        return [normalized] if normalized else []

    subjects = [match.group("subject"), *split_cross_subjects(match.group("cross_subjects"))]
    aliases = {normalized}
    for subject in subjects:
        for number_part in match.group("number").split("/"):
            aliases.add(f"{subject} {number_part}")
            if "-" in number_part:
                for lab_part in number_part.split("-"):
                    aliases.add(f"{subject} {lab_part}")
    return sorted(aliases)


def parse_credits(credit_hours: str):
    match = CREDIT_RE.search(credit_hours or "")
    if not match:
        return None
    minimum = float(match.group("credits"))
    maximum = float(match.group("max_credits")) if match.group("max_credits") else minimum
    if minimum.is_integer():
        minimum = int(minimum)
    if maximum.is_integer():
        maximum = int(maximum)
    return minimum if minimum == maximum else {"minimum": minimum, "maximum": maximum}


def load_raw_courses(raw_dir: Path) -> list[dict]:
    courses = []
    for path in sorted(raw_dir.glob("*.json")):
        with path.open(encoding="utf-8") as file:
            payload = json.load(file)
        for course in payload.get("courses", []):
            course["_source_file"] = path.name
            courses.append(course)
    return courses


def normalize_course(raw_course: dict) -> dict:
    course_code = normalize_course_code(raw_course.get("course_number", ""))
    subject, course_number, cross_subjects = split_subject_and_number(course_code)
    prerequisite_text = normalize_space(raw_course.get("prerequisite"))

    return {
        "course_code": course_code,
        "subject": subject,
        "course_number": course_number,
        "title": normalize_space(raw_course.get("course_name")),
        "credits": parse_credits(raw_course.get("credit_hours", "")),
        "credit_hours_text": normalize_space(raw_course.get("credit_hours")),
        "description": normalize_space(raw_course.get("description")),
        "prerequisites": prerequisite_text,
        "course_objective": normalize_space(raw_course.get("course_objective")),
        "topic_outline": normalize_space(raw_course.get("topic_outline")),
        "source_url": raw_course.get("source_url"),
        "aliases": expand_course_aliases(course_code),
        "cross_listed_subjects": cross_subjects,
        "source_file": raw_course.get("_source_file"),
    }


def normalize_courses(raw_dir: Path = DEFAULT_RAW_DIR) -> list[dict]:
    normalized_courses = []
    seen = set()
    for raw_course in load_raw_courses(raw_dir):
        normalized = normalize_course(raw_course)
        course_code = normalized["course_code"]
        if not course_code or course_code in seen:
            continue
        seen.add(course_code)
        normalized_courses.append(normalized)
    return normalized_courses


def write_json(path: Path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as file:
        json.dump(payload, file, indent=2, ensure_ascii=False)
        file.write("\n")


def main():
    parser = argparse.ArgumentParser(description="Normalize raw UGA course JSON into one catalog file.")
    parser.add_argument("--raw-dir", type=Path, default=DEFAULT_RAW_DIR)
    parser.add_argument("--output-path", type=Path, default=DEFAULT_OUTPUT_PATH)
    args = parser.parse_args()

    courses = normalize_courses(args.raw_dir)
    write_json(args.output_path, courses)
    print(
        json.dumps(
            {
                "course_count": len(courses),
                "output_path": str(args.output_path),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
