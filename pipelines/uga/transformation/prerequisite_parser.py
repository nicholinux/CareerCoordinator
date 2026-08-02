import json
import re


PARSER_VERSION = "prereq_parser_v1"
COURSE_REF_RE = re.compile(
    r"\b(?P<subject>[A-Z]{2,5})(?:\([A-Z]{2,5}\))*\s+"
    r"(?P<number>\d{4}[A-Z]?(?:-\d{4}[A-Z]?)?(?:/\d{4}[A-Z]?(?:-\d{4}[A-Z]?)?)?)\b"
)
GRADE_RE = re.compile(
    r"\b(?:minimum\s+grade\s+of|grade\s+of|minimum\s+grade)\s+([A-F][+-]?)\b",
    re.IGNORECASE,
)
UNSUPPORTED_RE = re.compile(
    r"\b(permission|honors|department|standing|placement|test score|consent)\b",
    re.IGNORECASE,
)
CO_REQUISITE_RE = re.compile(r"\b(co-?requisite|corequisite|co requisite)s?\b", re.IGNORECASE)


def normalize_course_id(course_code: str) -> str:
    match = COURSE_REF_RE.search(course_code or "")
    if not match:
        return ""

    subject = match.group("subject")
    number = match.group("number").split("/")[0].split("-")[0]
    if number.endswith("E"):
        number = number[:-1]
    return f"{subject}_{number}"


def extract_course_refs(text: str) -> list[str]:
    refs = []
    seen = set()
    for match in COURSE_REF_RE.finditer(text or ""):
        course_id = normalize_course_id(match.group(0))
        if course_id and course_id not in seen:
            refs.append(course_id)
            seen.add(course_id)
    return refs


def extract_course_ref_matches(text: str) -> list[dict]:
    matches = []
    seen = set()
    for match in COURSE_REF_RE.finditer(text or ""):
        course_id = normalize_course_id(match.group(0))
        if course_id and course_id not in seen:
            matches.append({"course_id": course_id, "raw": match.group(0)})
            seen.add(course_id)
    return matches


def detect_minimum_grade(text: str) -> str | None:
    match = GRADE_RE.search(text or "")
    return match.group(1).upper() if match else None


def detect_co_requisite_note(text: str) -> str | None:
    if CO_REQUISITE_RE.search(text or ""):
        return text
    return None


def _course_id_to_code(value: str) -> str:
    if re.fullmatch(r"[A-Z]{2,5}_\d{4}[A-Z]?", value or ""):
        subject, number = value.split("_", 1)
        return f"{subject} {number}"
    return value


def _stringify_prerequisite_value(value) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, list):
        parts = [_stringify_prerequisite_value(item) for item in value]
        return " and ".join(part for part in parts if part)
    if isinstance(value, dict):
        for key in ("raw_text", "text", "prerequisite", "prerequisites", "description"):
            if key in value:
                return _stringify_prerequisite_value(value[key])

        for key in ("all_of", "all", "and"):
            if key in value:
                children = value[key] if isinstance(value[key], list) else [value[key]]
                parts = [_stringify_prerequisite_value(item) for item in children]
                return " and ".join(part for part in parts if part)

        for key in ("one_of", "any_of", "or"):
            if key in value:
                children = value[key] if isinstance(value[key], list) else [value[key]]
                parts = [_stringify_prerequisite_value(item) for item in children]
                return " or ".join(part for part in parts if part)

        course_value = value.get("course_id") or value.get("course_code")
        if course_value:
            return _course_id_to_code(str(course_value).strip().upper())

        return json.dumps(value, sort_keys=True)
    return str(value).strip()


def _input_shape_notes(value, raw_text: str) -> list[str]:
    notes = []
    if isinstance(value, list):
        notes.append("array_prerequisites_input_normalized_as_and")
    elif isinstance(value, dict):
        notes.append("structured_prerequisites_input_normalized")

    co_requisite_note = detect_co_requisite_note(raw_text)
    if co_requisite_note:
        notes.append(f"co_requisite_note: {co_requisite_note}")
    return notes


def has_and(text: str) -> bool:
    return bool(re.search(r"\band\b", text or "", re.IGNORECASE))


def has_or(text: str) -> bool:
    return bool(re.search(r"\bor\b", text or "", re.IGNORECASE))


def has_mixed_logic(text: str) -> bool:
    return has_and(text) and has_or(text)


def has_explicit_grouping(text: str) -> bool:
    return bool(re.search(r"[\(\[].+?[\)\]]", text or ""))


def detect_logic_operator(text: str) -> str:
    refs = extract_course_refs(text)
    if len(refs) <= 1:
        return "SINGLE"
    if has_mixed_logic(text):
        return "UNKNOWN"
    if has_or(text):
        return "OR"
    if has_and(text):
        return "AND"
    return "AND"


def _has_unsupported_requirement(text: str) -> bool:
    return bool(UNSUPPORTED_RE.search(text or ""))


def _parent_operator(text: str) -> str | None:
    lowered = (text or "").lower()
    if re.search(r"[\)\]]\s+and\s+[\(\[]", lowered):
        return "AND"
    if re.search(r"[\)\]]\s+or\s+[\(\[]", lowered):
        return "OR"
    if re.search(r"[\)\]]\s+and\b", lowered) or re.search(r"\band\s+[\(\[]", lowered):
        return "AND"
    if re.search(r"[\)\]]\s+or\b", lowered) or re.search(r"\bor\s+[\(\[]", lowered):
        return "OR"
    if has_and(text):
        return "AND"
    if has_or(text):
        return "OR"
    return None


def _group_id(course_id: str, index: int) -> str:
    return f"{course_id}_group_{index}"


def _build_group(course_id: str, raw_text: str, group_text: str, index: int, parent_operator=None, status="parsed"):
    operator = detect_logic_operator(group_text)
    return {
        "requirement_group": _group_id(course_id, index),
        "course_id": course_id,
        "group_operator": operator,
        "parent_operator": parent_operator,
        "raw_text": raw_text,
        "parse_status": status,
        "parser_version": PARSER_VERSION,
    }


def _build_items(course_id: str, requirement_group: str, group_text: str, status="parsed") -> list[dict]:
    grade = detect_minimum_grade(group_text)
    return [
        {
            "requirement_group": requirement_group,
            "course_id": course_id,
            "prerequisite_course_id": match["course_id"],
            "condition_type": "course",
            "minimum_grade": grade,
            "raw_condition_text": match["raw"],
            "parse_status": status,
        }
        for match in extract_course_ref_matches(group_text)
    ]


def _empty_result(course_id: str, raw_text, status: str, reason: str, notes: list[str] | None = None):
    return {
        "groups": [],
        "items": [],
        "audit": {
            "course_id": course_id,
            "has_prerequisite_text": bool(raw_text),
            "raw_text": raw_text if raw_text else None,
            "parse_status": status,
            "groups_created": 0,
            "items_created": 0,
            "reason": reason,
            "notes": notes or [],
            "parser_version": PARSER_VERSION,
        },
    }


def _parse_explicit_groups(course_id: str, raw_text: str, notes: list[str] | None = None):
    groups = []
    items = []
    notes = notes or []
    parent = _parent_operator(raw_text)
    unsupported = _has_unsupported_requirement(raw_text)
    status = "partial" if unsupported else "parsed"
    reason = "Parsed explicit prerequisite groups."
    if unsupported:
        reason = "Parsed course prerequisites; unsupported non-course requirement ignored."

    grouped_matches = list(re.finditer(r"[\(\[]([^\)\]]+)[\)\]]", raw_text))
    consumed_spans = []
    for match in grouped_matches:
        group_text = match.group(1)
        consumed_spans.append(match.span())
        if has_mixed_logic(group_text):
            return _empty_result(
                course_id,
                raw_text,
                "needs_review",
                "Mixed AND/OR prerequisite inside explicit group.",
                notes,
            )
        if not extract_course_refs(group_text):
            continue
        group = _build_group(course_id, raw_text, group_text, len(groups) + 1, parent, status)
        groups.append(group)
        items.extend(_build_items(course_id, group["requirement_group"], group_text, "parsed"))

    remainder_parts = []
    cursor = 0
    for start, end in consumed_spans:
        remainder_parts.append(raw_text[cursor:start])
        cursor = end
    remainder_parts.append(raw_text[cursor:])
    remainder = " ".join(remainder_parts)

    if extract_course_refs(remainder):
        if has_mixed_logic(remainder):
            return _empty_result(
                course_id,
                raw_text,
                "needs_review",
                "Mixed AND/OR prerequisite without explicit grouping in remainder.",
                notes,
            )
        group = _build_group(course_id, raw_text, remainder, len(groups) + 1, parent, status)
        groups.append(group)
        items.extend(_build_items(course_id, group["requirement_group"], remainder, "parsed"))

    if not groups:
        return _empty_result(
            course_id,
            raw_text,
            "needs_review",
            "Prerequisite text contains no supported course requirement.",
            notes,
        )

    return _result(course_id, raw_text, groups, items, status, reason, notes)


def _result(
    course_id: str,
    raw_text: str,
    groups: list[dict],
    items: list[dict],
    status: str,
    reason: str,
    notes: list[str] | None = None,
):
    return {
        "groups": groups,
        "items": items,
        "audit": {
            "course_id": course_id,
            "has_prerequisite_text": True,
            "raw_text": raw_text,
            "parse_status": status,
            "groups_created": len(groups),
            "items_created": len(items),
            "reason": reason,
            "notes": notes or [],
            "parser_version": PARSER_VERSION,
        },
    }


def parse_prerequisites(course_record: dict) -> dict:
    course_id = normalize_course_id(course_record.get("course_number", ""))
    raw_prerequisite = course_record.get("prerequisite")
    raw_text = _stringify_prerequisite_value(raw_prerequisite)
    notes = _input_shape_notes(raw_prerequisite, raw_text)

    if not raw_text:
        return _empty_result(course_id, None, "no_prerequisite", "No prerequisite text found.", notes)

    if not extract_course_refs(raw_text):
        return _empty_result(
            course_id,
            raw_text,
            "needs_review",
            "Prerequisite text contains no supported course requirement.",
            notes,
        )

    if has_mixed_logic(raw_text) and not has_explicit_grouping(raw_text):
        return _empty_result(
            course_id,
            raw_text,
            "needs_review",
            "Mixed AND/OR prerequisite without explicit grouping.",
            notes,
        )

    if has_mixed_logic(raw_text) and has_explicit_grouping(raw_text):
        return _parse_explicit_groups(course_id, raw_text, notes)

    unsupported = _has_unsupported_requirement(raw_text)
    status = "partial" if unsupported else "parsed"
    reason = "Parsed prerequisite course references."
    if unsupported:
        reason = "Parsed course prerequisites; unsupported non-course requirement ignored."

    group = _build_group(course_id, raw_text, raw_text, 1, None, status)
    items = _build_items(course_id, group["requirement_group"], raw_text, "parsed")
    return _result(course_id, raw_text, [group], items, status, reason, notes)
