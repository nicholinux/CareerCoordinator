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


def _empty_result(course_id: str, raw_text, status: str, reason: str):
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
            "parser_version": PARSER_VERSION,
        },
    }


def _parse_explicit_groups(course_id: str, raw_text: str):
    groups = []
    items = []
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
        )

    return _result(course_id, raw_text, groups, items, status, reason)


def _result(course_id: str, raw_text: str, groups: list[dict], items: list[dict], status: str, reason: str):
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
            "parser_version": PARSER_VERSION,
        },
    }


def parse_prerequisites(course_record: dict) -> dict:
    course_id = normalize_course_id(course_record.get("course_number", ""))
    raw_text = course_record.get("prerequisite") or ""

    if not raw_text:
        return _empty_result(course_id, None, "no_prerequisite", "No prerequisite text found.")

    if not extract_course_refs(raw_text):
        return _empty_result(
            course_id,
            raw_text,
            "needs_review",
            "Prerequisite text contains no supported course requirement.",
        )

    if has_mixed_logic(raw_text) and not has_explicit_grouping(raw_text):
        return _empty_result(
            course_id,
            raw_text,
            "needs_review",
            "Mixed AND/OR prerequisite without explicit grouping.",
        )

    if has_mixed_logic(raw_text) and has_explicit_grouping(raw_text):
        return _parse_explicit_groups(course_id, raw_text)

    unsupported = _has_unsupported_requirement(raw_text)
    status = "partial" if unsupported else "parsed"
    reason = "Parsed prerequisite course references."
    if unsupported:
        reason = "Parsed course prerequisites; unsupported non-course requirement ignored."

    group = _build_group(course_id, raw_text, raw_text, 1, None, status)
    items = _build_items(course_id, group["requirement_group"], raw_text, "parsed")
    return _result(course_id, raw_text, [group], items, status, reason)
