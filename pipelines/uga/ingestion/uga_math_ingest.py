import json
import time
from html import unescape
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlencode, urljoin
from urllib.request import Request, build_opener


BASE_URL = "https://bulletin.uga.edu"
LIST_URL = f"{BASE_URL}/Course/_ViewAllCourses"
COURSE_PREFIX = "MATH"
START_PAGE = 1
END_PAGE = 3
DETAIL_REQUEST_DELAY_SECONDS = 1.5
PAGE_REQUEST_DELAY_SECONDS = 3
ROOT_DIR = Path(__file__).resolve().parents[3]
OUTPUT_PATH = ROOT_DIR / "data" / "raw" / "uga" / "uga_math_courses_pages_1_to_3.json"


class Node:
    def __init__(self, tag, attrs=None):
        self.tag = tag
        self.attrs = dict(attrs or [])
        self.children = []
        self.text_parts = []

    def classes(self):
        return set((self.attrs.get("class") or "").split())

    def text(self, separator=" "):
        parts = list(self.text_parts)
        for child in self.children:
            child_text = child.text(separator)
            if child_text:
                parts.append(child_text)
        return clean(separator.join(parts))


class TreeParser(HTMLParser):
    VOID_TAGS = {
        "area",
        "base",
        "br",
        "col",
        "embed",
        "hr",
        "img",
        "input",
        "link",
        "meta",
        "param",
        "source",
        "track",
        "wbr",
    }

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.root = Node("document")
        self.stack = [self.root]

    def handle_starttag(self, tag, attrs):
        node = Node(tag, attrs)
        self.stack[-1].children.append(node)
        if tag not in self.VOID_TAGS:
            self.stack.append(node)

    def handle_endtag(self, tag):
        for index in range(len(self.stack) - 1, 0, -1):
            if self.stack[index].tag == tag:
                del self.stack[index:]
                break

    def handle_data(self, data):
        if data.strip():
            self.stack[-1].text_parts.append(data)


def clean(value):
    return " ".join(unescape(value or "").split())


def parse_html(html):
    parser = TreeParser()
    parser.feed(html)
    return parser.root


def has_class(node, class_name):
    return class_name in node.classes()


def find_all(node, predicate):
    matches = []
    if predicate(node):
        matches.append(node)
    for child in node.children:
        matches.extend(find_all(child, predicate))
    return matches


def first(node, predicate):
    if predicate(node):
        return node
    for child in node.children:
        found = first(child, predicate)
        if found:
            return found
    return None


def request_text(opener, url, data=None):
    headers = {
        "User-Agent": "Course research scraper; contact: local test run",
        "Accept": "text/html,application/xhtml+xml",
    }
    encoded_data = urlencode(data, doseq=True).encode("utf-8") if data else None
    request = Request(url, data=encoded_data, headers=headers, method="POST" if data else "GET")
    with opener.open(request, timeout=30) as response:
        return response.read().decode("utf-8", errors="replace")


def extract_course_links(list_html):
    root = parse_html(list_html)
    links = []
    seen = set()
    for card in find_all(root, lambda n: has_class(n, "course-card")):
        course_number_node = first(card, lambda n: n.tag == "a" and has_class(n, "crn"))
        course_number = course_number_node.text(" ") if course_number_node else ""
        if course_number.endswith("E"):
            continue

        detail_link = first(card, lambda n: n.tag == "a" and has_class(n, "full-description"))
        href = detail_link.attrs.get("href") if detail_link else None
        if href:
            absolute_url = urljoin(BASE_URL, href)
            if absolute_url not in seen:
                links.append(absolute_url)
                seen.add(absolute_url)
    return links


def text_from_next_content(label_node):
    siblings = label_node.parent.children if label_node.parent else []
    try:
        label_index = siblings.index(label_node)
    except ValueError:
        return ""

    for sibling in siblings[label_index + 1 :]:
        if sibling.tag == "hr":
            continue
        if sibling.tag == "p":
            return sibling.text(" ")
        if sibling.tag == "ul":
            return "\n".join(child.text(" ") for child in sibling.children if child.tag == "li")
        if sibling.text():
            return sibling.text(" ")
    return ""


def attach_parents(node, parent=None):
    node.parent = parent
    for child in node.children:
        attach_parents(child, node)


def field_after_label(root, labels):
    wanted = {label.lower() for label in labels}
    for node in find_all(root, lambda n: n.tag == "p" and has_class(n, "large-mws")):
        if node.text(" ").lower() in wanted:
            return text_from_next_content(node)
    return ""


def parse_course_detail(detail_html, source_url):
    root = parse_html(detail_html)
    attach_parents(root)

    course_number_node = first(root, lambda n: n.tag == "li" and has_class(n, "crn"))
    credit_node = first(root, lambda n: n.tag == "li" and has_class(n, "credit-number"))
    title_node = first(root, lambda n: n.tag == "h1" and has_class(n, "courses"))

    return {
        "course_name": title_node.text(" ") if title_node else "",
        "course_number": course_number_node.text(" ") if course_number_node else "",
        "credit_hours": credit_node.text(" ") if credit_node else "",
        "prerequisite": field_after_label(root, ["Prerequisite", "Prerequisites"]),
        "course_objective": field_after_label(root, ["Course Objectives", "Student learning Outcomes"]),
        "topic_outline": field_after_label(root, ["Topical Outline"]),
        "source_url": source_url,
    }


def main():
    opener = build_opener()
    courses = []
    seen_detail_urls = set()

    for page in range(START_PAGE, END_PAGE + 1):
        print(f"Fetching list page {page}")
        list_html = request_text(opener, LIST_URL, {"page": page, "coursePrefix": COURSE_PREFIX})
        detail_urls = extract_course_links(list_html)

        for index, detail_url in enumerate(detail_urls, start=1):
            if detail_url in seen_detail_urls:
                continue

            seen_detail_urls.add(detail_url)
            print(f"[page {page}: {index}/{len(detail_urls)}] Fetching {detail_url}")
            detail_html = request_text(opener, detail_url)
            courses.append(parse_course_detail(detail_html, detail_url))
            time.sleep(DETAIL_REQUEST_DELAY_SECONDS)

        if page < END_PAGE:
            time.sleep(PAGE_REQUEST_DELAY_SECONDS)

    payload = {
        "source": LIST_URL,
        "course_prefix": COURSE_PREFIX,
        "start_page": START_PAGE,
        "end_page": END_PAGE,
        "count": len(courses),
        "courses": courses,
    }
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Saved {len(courses)} courses to {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
