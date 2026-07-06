import argparse
import json
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[3]
DEFAULT_RAW_DIR = ROOT_DIR / "data" / "raw" / "uga"
DEFAULT_OUTPUT_PATH = ROOT_DIR / "data" / "processed" / "uga" / "courses" / "course_names_by_subject.json"
RAW_COURSE_FILES = {
    "CSCI": "uga_csci_courses_pages_1_to_6.json",
    "MATH": "uga_math_courses_pages_1_to_3.json",
    "STAT": "uga_stat_courses_pages_1_to_3.json",
}


def load_courses_by_subject(raw_dir: Path) -> dict[str, list[dict]]:
    courses_by_subject = {}

    for subject, filename in RAW_COURSE_FILES.items():
        path = raw_dir / filename
        with path.open(encoding="utf-8") as file:
            payload = json.load(file)

        courses = []
        for course in payload.get("courses", []):
            course_number = course.get("course_number")
            course_name = course.get("course_name")
            if not course_number or not course_name:
                continue

            courses.append(
                {
                    "course_number": course_number,
                    "course_name": course_name,
                }
            )

        courses_by_subject[subject] = courses

    return courses_by_subject


def write_json(path: Path, payload: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as file:
        json.dump(payload, file, indent=2, ensure_ascii=False)
        file.write("\n")


def main():
    parser = argparse.ArgumentParser(description="Extract UGA course names grouped by subject.")
    parser.add_argument("--raw-dir", type=Path, default=DEFAULT_RAW_DIR)
    parser.add_argument("--output-path", type=Path, default=DEFAULT_OUTPUT_PATH)
    args = parser.parse_args()

    courses_by_subject = load_courses_by_subject(args.raw_dir)
    write_json(args.output_path, courses_by_subject)

    print(
        json.dumps(
            {
                "subjects": sorted(courses_by_subject),
                "course_counts": {
                    subject: len(courses)
                    for subject, courses in sorted(courses_by_subject.items())
                },
                "output_path": str(args.output_path),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
