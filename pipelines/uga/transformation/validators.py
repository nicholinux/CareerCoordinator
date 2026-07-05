from collections import Counter, defaultdict


def validate_prerequisite_outputs(course_ids, groups, items, audit):
    errors = []
    course_id_set = set(course_ids)

    audit_counts = Counter(row.get("course_id") for row in audit)
    missing_audit = sorted(course_id_set - set(audit_counts))
    duplicate_audit = sorted(course_id for course_id, count in audit_counts.items() if count != 1)
    if missing_audit:
        errors.append(f"Missing audit rows for: {', '.join(missing_audit)}")
    if duplicate_audit:
        errors.append(f"Duplicate audit rows for: {', '.join(duplicate_audit)}")

    group_ids = {group.get("requirement_group") for group in groups}
    for group in groups:
        if group.get("course_id") not in course_id_set:
            errors.append(f"Group references unknown course_id: {group.get('course_id')}")

    for item in items:
        if item.get("course_id") not in course_id_set:
            errors.append(f"Item references unknown course_id: {item.get('course_id')}")
        if item.get("requirement_group") not in group_ids:
            errors.append(f"Item references missing group: {item.get('requirement_group')}")
        if "is_resolved" not in item:
            errors.append(f"Item missing is_resolved marker: {item.get('course_id')}")

    item_counts_by_group = Counter(item.get("requirement_group") for item in items)
    for group in groups:
        requirement_group = group.get("requirement_group")
        if item_counts_by_group[requirement_group] == 0:
            errors.append(f"Group has no items: {requirement_group}")

    group_counts_by_course = Counter(group.get("course_id") for group in groups)
    item_counts_by_course = Counter(item.get("course_id") for item in items)
    for audit_row in audit:
        course_id = audit_row.get("course_id")
        if audit_row.get("parse_status") == "no_prerequisite":
            if group_counts_by_course[course_id] != 0 or item_counts_by_course[course_id] != 0:
                errors.append(f"No-prerequisite course emitted groups/items: {course_id}")

    for audit_row in audit:
        if audit_row.get("parse_status") == "needs_review":
            raw_text = (audit_row.get("raw_text") or "").lower()
            if " and " in raw_text and " or " in raw_text and not any(char in raw_text for char in "()[]"):
                continue

    raw_text_by_course = defaultdict(set)
    for group in groups:
        raw_text_by_course[group.get("course_id")].add(group.get("raw_text"))
    for audit_row in audit:
        raw_text = audit_row.get("raw_text")
        course_id = audit_row.get("course_id")
        if raw_text and group_counts_by_course[course_id] and raw_text not in raw_text_by_course[course_id]:
            errors.append(f"Group raw text does not preserve audit raw text for: {course_id}")

    return errors
