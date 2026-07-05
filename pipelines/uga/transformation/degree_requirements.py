import argparse
import json
import re
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[3]
DEFAULT_RAW_DIR = ROOT_DIR / "data" / "raw" / "uga"
DEFAULT_OUTPUT_PATH = (
    ROOT_DIR
    / "data"
    / "processed"
    / "uga"
    / "degree_requirements"
    / "degree_requirements_normalized.json"
)


COURSE_CODE_RE = re.compile(
    r"^(?P<subject>[A-Z]{2,5})(?:\((?P<cross_subjects>[A-Z()]+)\))?\s+"
    r"(?P<number>[0-9A-Z/\-]+)$"
)


def split_cross_subjects(value: str | None) -> list[str]:
    if not value:
        return []
    return re.findall(r"[A-Z]{2,5}", value)


def expand_course_aliases(course_code: str) -> set[str]:
    match = COURSE_CODE_RE.match(course_code.strip())
    if not match:
        return {course_code.strip()}

    subjects = [match.group("subject"), *split_cross_subjects(match.group("cross_subjects"))]
    number_text = match.group("number")
    number_parts = number_text.split("/")
    aliases = set()

    for subject in subjects:
        for number_part in number_parts:
            if "-" in number_part:
                aliases.add(f"{subject} {number_part}")
                for lab_part in number_part.split("-"):
                    aliases.add(f"{subject} {lab_part}")
            else:
                aliases.add(f"{subject} {number_part}")

    return aliases


def load_catalog_course_codes(raw_dir: Path) -> set[str]:
    course_codes = set()
    for path in sorted(raw_dir.glob("*.json")):
        with path.open(encoding="utf-8") as file:
            payload = json.load(file)

        for course in payload.get("courses", []):
            course_number = course.get("course_number")
            if not course_number:
                continue
            course_codes.update(expand_course_aliases(course_number))

    return course_codes


def all_requirement_course_codes(requirements: list[dict]) -> list[str]:
    course_codes = []
    for requirement in requirements:
        course_codes.extend(requirement.get("courses", []))
    return course_codes


def build_degree_requirements(raw_dir: Path = DEFAULT_RAW_DIR) -> dict:
    requirements = [
        {
            "id": "area_vi_requirements",
            "name": "Area VI Requirements for Computer Science",
            "type": "all_of",
            "courses": ["CSCI 1302", "CSCI 2670", "CSCI 2720", "MATH 2250"],
        },
        {
            "id": "computing_and_society",
            "name": "Computing & Society",
            "type": "all_of",
            "courses": ["CSCI 3030"],
        },
        {
            "id": "computer_architecture",
            "name": "Computer Architecture",
            "type": "all_of",
            "courses": ["CSCI 4720"],
        },
        {
            "id": "algorithms",
            "name": "Algorithms",
            "type": "all_of",
            "courses": ["CSCI 4470"],
        },
        {
            "id": "application_design",
            "name": "Application Design",
            "type": "one_of",
            "courses": ["CSCI 4050", "CSCI 4370"],
        },
        {
            "id": "systems_design",
            "name": "Systems Design",
            "type": "one_of",
            "courses": ["CSCI 4570", "CSCI 4730", "CSCI 4760"],
        },
        {
            "id": "major_electives",
            "name": "Major Electives",
            "type": "minimum_credits",
            "minimum_credits": 12,
            "course_filter": {
                "subject": "CSCI",
                "minimum_level": 4000,
                "maximum_level": 4999,
            },
            "exclusions": {
                "exclude_courses_used_by_requirement_ids": [
                    "computing_and_society",
                    "computer_architecture",
                    "algorithms",
                    "application_design",
                    "systems_design",
                ]
            },
            "notes": [
                "CSCI 4000-level courses already taken to fulfill another CSCI requirement should not be counted toward major electives."
            ],
        },
        {
            "id": "major_related_electives_math",
            "name": "Major Related Electives: Math",
            "type": "minimum_credits",
            "minimum_credits": 11,
            "courses": [
                "CSCI 2150",
                "CSCI 2150L",
                "CSCI 4150",
                "CSCI 6150",
                "MATH 2260",
                "MATH 2270",
                "MATH 2400",
                "MATH 2410",
                "MATH 2410H",
                "MATH 2500",
                "MATH 2700",
                "MATH 3000",
                "MATH 3300",
                "MATH 3500",
                "MATH 3500H",
                "MATH 3510",
                "MATH 3510H",
                "STAT 2000",
                "STAT 4210",
            ],
            "notes": [
                "Choosing 7 hours from upper-division coursework helps satisfy the 39-hour upper-division coursework requirement.",
                "If MATH 2260 or STAT 2000 was used to satisfy core curriculum requirements, another course must be selected for this requirement.",
            ],
        },
        {
            "id": "teamwork_requirement",
            "name": "Teamwork Requirement",
            "type": "one_of",
            "courses": ["CSCI 4050", "CSCI 4300", "CSCI 4530", "CSCI 4800"],
            "overlap_allowed": True,
            "notes": ["This course may overlap with another CSCI requirement."],
        },
    ]

    catalog_course_codes = load_catalog_course_codes(raw_dir)
    unresolved_courses = sorted(
        course_code
        for course_code in set(all_requirement_course_codes(requirements))
        if course_code not in catalog_course_codes
    )

    return {
        "program": {
            "institution": "University of Georgia",
            "degree": "BS",
            "major": "Computer Science",
        },
        "requirements": requirements,
        "unresolved_courses": unresolved_courses,
    }


def write_json(path: Path, payload: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as file:
        json.dump(payload, file, indent=2, ensure_ascii=False)
        file.write("\n")


def main():
    parser = argparse.ArgumentParser(description="Build normalized UGA degree requirements JSON.")
    parser.add_argument("--raw-dir", type=Path, default=DEFAULT_RAW_DIR)
    parser.add_argument("--output-path", type=Path, default=DEFAULT_OUTPUT_PATH)
    args = parser.parse_args()

    payload = build_degree_requirements(args.raw_dir)
    write_json(args.output_path, payload)
    print(
        json.dumps(
            {
                "requirements": len(payload["requirements"]),
                "unresolved_courses": len(payload["unresolved_courses"]),
                "output_path": str(args.output_path),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
