import argparse
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any


ROOT_DIR = Path(__file__).resolve().parents[2]
DEFAULT_COURSES_PATH = ROOT_DIR / "data" / "processed" / "uga" / "courses"
DEFAULT_CATALOGS_PATH = None
DEFAULT_REQUIREMENTS_PATH = ROOT_DIR / "data" / "processed" / "uga" / "degree_requirements"
DEFAULT_REPORT_PATH = (
    ROOT_DIR
    / "data"
    / "processed"
    / "uga"
    / "validation"
    / "curriculum_input_validation_report.json"
)

SUPPORTED_REQUIREMENT_TYPES = {"all_of", "one_of", "minimum_credits", "note"}
COURSE_CODE_RE = re.compile(r"\b[A-Z]{2,5}\s+\d{4}[A-Z]?\b", re.IGNORECASE)
COURSE_CODE_PARTS_RE = re.compile(
    r"^(?P<subject>[A-Z]{2,5})(?:\((?P<cross_subjects>[A-Z()]+)\))?\s+"
    r"(?P<number>[0-9A-Z/\-]+)$"
)


def load_json(path: Path):
    try:
        with path.open(encoding="utf-8") as file:
            return json.load(file), None
    except FileNotFoundError:
        return None, f"Missing input file: {path}"
    except json.JSONDecodeError as error:
        return None, f"Invalid JSON in {path}: {error}"
    except OSError as error:
        return None, f"Unable to read {path}: {error}"


def load_first_json_from_directory(path: Path, preferred_filename: str):
    preferred_path = path / preferred_filename
    if preferred_path.exists():
        return load_json(preferred_path)

    json_files = sorted(path.glob("*.json"))
    if not json_files:
        return None, f"No JSON files found in directory: {path}"
    return load_json(json_files[0])


def load_courses_input(path: Path):
    if path.is_dir():
        return load_first_json_from_directory(path, "course_names_by_subject.json")
    return load_json(path)


def load_requirements_input(path: Path):
    if path.is_dir():
        return load_first_json_from_directory(path, "degree_requirements_normalized.json")
    return load_json(path)


def normalize_course_code(code: Any) -> str:
    if not isinstance(code, str):
        return ""
    return re.sub(r"\s+", " ", code.strip().upper())


def split_subject_and_number(course_code: str):
    normalized = normalize_course_code(course_code)
    parts = normalized.split(" ", 1)
    if len(parts) != 2:
        return "", normalized
    return parts[0], parts[1]


def split_cross_subjects(value: str | None) -> list[str]:
    if not value:
        return []
    return re.findall(r"[A-Z]{2,5}", value)


def expand_course_code_aliases(course_code: str) -> set[str]:
    normalized = normalize_course_code(course_code)
    match = COURSE_CODE_PARTS_RE.match(normalized)
    if not match:
        return {normalized} if normalized else set()

    subjects = [match.group("subject"), *split_cross_subjects(match.group("cross_subjects"))]
    aliases = {normalized}
    for subject in subjects:
        for number_part in match.group("number").split("/"):
            aliases.add(f"{subject} {number_part}")
            if "-" in number_part:
                for lab_part in number_part.split("-"):
                    aliases.add(f"{subject} {lab_part}")
    return aliases


def course_list_from_payload(payload: Any):
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict) and isinstance(payload.get("courses"), list):
        return payload["courses"]
    if isinstance(payload, dict) and all(isinstance(value, list) for value in payload.values()):
        courses = []
        seen_course_codes = set()
        for subject, subject_courses in payload.items():
            for course in subject_courses:
                if not isinstance(course, dict):
                    continue
                course_code = normalize_course_code(course.get("course_number"))
                if not course_code or course_code in seen_course_codes:
                    continue
                seen_course_codes.add(course_code)
                course_subject, course_number = split_subject_and_number(course_code)
                courses.append(
                    {
                        "course_code": course_code,
                        "subject": course_subject or normalize_course_code(subject),
                        "course_number": course_number,
                        "title": course.get("course_name"),
                        "credits": course.get("credits"),
                        "prerequisites": course.get("prerequisites", []),
                    }
                )
        return courses
    return None


def build_course_lookup(courses: list[dict]) -> set[str]:
    lookup = set()
    for course in courses:
        lookup.update(expand_course_code_aliases(course.get("course_code", "")))
    return lookup


def extract_course_code_from_reference(reference: Any) -> str | None:
    if isinstance(reference, str):
        return normalize_course_code(reference)
    if isinstance(reference, dict):
        return normalize_course_code(reference.get("course_code"))
    return None


def extract_requirement_course_codes(requirements: list[dict]) -> set[str]:
    course_codes = set()
    for requirement in requirements:
        for field in ("courses", "required_courses", "allowed_courses"):
            references = requirement.get(field)
            if not isinstance(references, list):
                continue
            for reference in references:
                course_code = extract_course_code_from_reference(reference)
                if course_code:
                    course_codes.add(course_code)
    return course_codes


def extract_prerequisite_course_codes(prereq: Any) -> set[str]:
    course_codes = set()

    if prereq in (None, "", []):
        return course_codes

    if isinstance(prereq, dict) and prereq.get("type") == "none":
        return course_codes

    if isinstance(prereq, str):
        return {normalize_course_code(match.group(0)) for match in COURSE_CODE_RE.finditer(prereq)}

    if isinstance(prereq, list):
        for item in prereq:
            course_codes.update(extract_prerequisite_course_codes(item))
        return course_codes

    if isinstance(prereq, dict):
        for field in ("course_code", "courses", "required_courses", "allowed_courses", "requirements"):
            value = prereq.get(field)
            if value is not None:
                course_codes.update(extract_prerequisite_course_codes(value))
        return course_codes

    return course_codes


def validate_course_records(courses: list[dict]):
    invalid_records = []
    normalized_codes = []

    for index, course in enumerate(courses):
        reasons = []
        if not isinstance(course, dict):
            invalid_records.append({"index": index, "reasons": ["Course record is not an object."]})
            continue

        course_code = normalize_course_code(course.get("course_code"))
        subject = normalize_course_code(course.get("subject"))
        course_number = normalize_course_code(course.get("course_number"))

        if not course_code:
            reasons.append("Missing course_code.")
        if not subject:
            reasons.append("Missing subject.")
        if not course_number:
            reasons.append("Missing course_number.")
        if not course.get("title"):
            reasons.append("Missing title.")
        if "prerequisites" not in course:
            reasons.append("Missing prerequisites field.")
        if course_code and subject and course_number:
            expected = normalize_course_code(f"{subject} {course_number}")
            if course_code != expected:
                reasons.append(f"course_code does not match subject + course_number: expected {expected}.")

        if course_code:
            normalized_codes.append(course_code)
        if reasons:
            invalid_records.append({"index": index, "course_code": course_code or None, "reasons": reasons})

    duplicates = sorted(code for code, count in Counter(normalized_codes).items() if count > 1)
    return invalid_records, duplicates


def resolve_course_filter(course_filter: dict, courses: list[dict]) -> list[str]:
    subject = normalize_course_code(course_filter.get("subject"))
    minimum_level = course_filter.get("minimum_level")
    maximum_level = course_filter.get("maximum_level")
    matches = []

    for course in courses:
        course_subject = normalize_course_code(course.get("subject"))
        course_number = normalize_course_code(course.get("course_number"))
        level_match = re.search(r"\d{4}", course_number)
        if subject and course_subject != subject:
            continue
        if not level_match:
            continue
        level = int(level_match.group(0))
        if minimum_level is not None and level < int(minimum_level):
            continue
        if maximum_level is not None and level > int(maximum_level):
            continue
        matches.append(normalize_course_code(course.get("course_code")))

    return matches


def validate_requirement_groups(requirements: list[dict], courses: list[dict]):
    invalid_groups = []
    empty_filters = []

    for index, requirement in enumerate(requirements):
        reasons = []
        requirement_id = requirement.get("id") if isinstance(requirement, dict) else None
        if not isinstance(requirement, dict):
            invalid_groups.append({"index": index, "id": None, "reasons": ["Requirement is not an object."]})
            continue

        group_type = requirement.get("type")
        if not requirement.get("id"):
            reasons.append("Missing id.")
        if not requirement.get("name"):
            reasons.append("Missing name.")
        if not group_type:
            reasons.append("Missing type.")
        elif group_type not in SUPPORTED_REQUIREMENT_TYPES:
            reasons.append(f"Unsupported type: {group_type}.")

        courses_list = requirement.get("courses")
        required_courses = requirement.get("required_courses")
        allowed_courses = requirement.get("allowed_courses")

        if group_type == "all_of" and not (courses_list or required_courses):
            reasons.append("all_of must include courses or required_courses.")
        elif group_type == "one_of":
            options = courses_list or allowed_courses or []
            if not isinstance(options, list) or len(options) < 2:
                reasons.append("one_of should include at least two course options.")
        elif group_type == "minimum_credits":
            if "minimum_credits" not in requirement:
                reasons.append("minimum_credits group is missing minimum_credits.")
            if not (courses_list or allowed_courses or requirement.get("course_filter")):
                reasons.append("minimum_credits must include courses, allowed_courses, or course_filter.")
            course_filter = requirement.get("course_filter")
            if course_filter:
                if not (course_filter.get("subject") or course_filter.get("minimum_level")):
                    reasons.append("course_filter must include subject or minimum_level.")
                elif not resolve_course_filter(course_filter, courses):
                    empty_filters.append(requirement_id)
        elif group_type == "note" and not (requirement.get("notes") or requirement.get("description")):
            reasons.append("note must include notes or description.")

        if reasons:
            invalid_groups.append({"index": index, "id": requirement_id, "reasons": reasons})

    return invalid_groups, empty_filters


def build_report(
    courses,
    requirements,
    missing_requirement_courses,
    missing_prerequisite_courses,
    duplicate_courses,
    invalid_course_records,
    invalid_requirement_groups,
    empty_course_filters,
    warnings,
    errors,
    strict,
):
    valid = not (
        errors
        or duplicate_courses
        or missing_requirement_courses
        or invalid_requirement_groups
        or empty_course_filters
        or (strict and missing_prerequisite_courses)
    )

    if len(invalid_course_records) > max(10, len(courses) // 2):
        valid = False

    return {
        "valid": valid,
        "summary": {
            "course_count": len(courses),
            "requirement_group_count": len(requirements),
            "explicit_requirement_course_count": len(extract_requirement_course_codes(requirements)),
            "prerequisite_reference_count": sum(
                len(extract_prerequisite_course_codes(course.get("prerequisites"))) for course in courses
            ),
            "missing_requirement_course_count": len(missing_requirement_courses),
            "missing_prerequisite_course_count": len(missing_prerequisite_courses),
            "invalid_requirement_group_count": len(invalid_requirement_groups),
            "duplicate_course_count": len(duplicate_courses),
        },
        "missing_requirement_courses": missing_requirement_courses,
        "missing_prerequisite_courses": missing_prerequisite_courses,
        "duplicate_courses": duplicate_courses,
        "invalid_course_records": invalid_course_records,
        "invalid_requirement_groups": invalid_requirement_groups,
        "empty_course_filters": empty_course_filters,
        "warnings": warnings,
        "errors": errors,
    }


def write_report(path: Path, report: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as file:
        json.dump(report, file, indent=2, ensure_ascii=False)
        file.write("\n")


def main():
    parser = argparse.ArgumentParser(description="Validate curriculum input JSON files.")
    parser.add_argument("--courses", type=Path, default=DEFAULT_COURSES_PATH)
    parser.add_argument("--catalogs", type=Path, default=DEFAULT_CATALOGS_PATH)
    parser.add_argument("--requirements", type=Path, default=DEFAULT_REQUIREMENTS_PATH)
    parser.add_argument("--output", type=Path, default=DEFAULT_REPORT_PATH)
    parser.add_argument("--strict", action="store_true")
    args = parser.parse_args()

    errors = []
    warnings = []
    courses_payload, error = load_courses_input(args.courses)
    if error:
        errors.append(error)
    catalogs_payload = None
    if args.catalogs:
        catalogs_payload, error = load_json(args.catalogs)
        if error:
            errors.append(error)
    requirements_payload, error = load_requirements_input(args.requirements)
    if error:
        errors.append(error)

    courses = course_list_from_payload(courses_payload) if not errors else []
    if courses_payload is not None and courses is None:
        errors.append(f"{args.courses} is not parseable as a course list.")
        courses = []

    requirements = []
    if isinstance(requirements_payload, dict) and isinstance(requirements_payload.get("requirements"), list):
        requirements = requirements_payload["requirements"]
    elif requirements_payload is not None:
        errors.append(f"{args.requirements} has no requirements array.")

    invalid_course_records, duplicate_courses = validate_course_records(courses)
    invalid_requirement_groups, empty_course_filters = validate_requirement_groups(requirements, courses)
    course_lookup = build_course_lookup(courses)

    requirement_course_codes = extract_requirement_course_codes(requirements)
    missing_requirement_courses = sorted(code for code in requirement_course_codes if code not in course_lookup)

    prerequisite_course_codes = set()
    for course in courses:
        prerequisite_course_codes.update(extract_prerequisite_course_codes(course.get("prerequisites")))
    missing_prerequisite_courses = sorted(code for code in prerequisite_course_codes if code not in course_lookup)

    if missing_prerequisite_courses:
        warnings.append("Some prerequisite courses are not present in the normalized course list.")
    if catalogs_payload is not None and not isinstance(catalogs_payload, (dict, list)):
        warnings.append("course_catalogs.json contains an unexpected top-level JSON type.")

    report = build_report(
        courses,
        requirements,
        missing_requirement_courses,
        missing_prerequisite_courses,
        duplicate_courses,
        invalid_course_records,
        invalid_requirement_groups,
        empty_course_filters,
        warnings,
        errors,
        args.strict,
    )
    write_report(args.output, report)

    print("Curriculum input validation complete.")
    print(f"Valid: {str(report['valid']).lower()}")
    print(f"Courses: {report['summary']['course_count']}")
    print(f"Requirement groups: {report['summary']['requirement_group_count']}")
    print(f"Missing requirement courses: {report['summary']['missing_requirement_course_count']}")
    print(f"Missing prerequisite courses: {report['summary']['missing_prerequisite_course_count']}")
    print(f"Invalid requirement groups: {report['summary']['invalid_requirement_group_count']}")
    print(f"Report written to: {args.output}")


if __name__ == "__main__":
    main()
