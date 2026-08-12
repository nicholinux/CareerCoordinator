# CareerCoordinator

Before formally beginning their education in computer science, many students may already have a specialty in mind that they'd like to pursue. Despite this, CS curriculums are design with the intent of equipping students with a generalist skillset to provide their students with the most broad range of opportunities possible. Electives make it possible for undergrads to gain exposure to the many subfields that CS has to offer, but it is up to the student to elucidate the most important competencies needed to land their desired job.

CareerCoordinator serves as a one-stop-shop for students that want to know not just the courses they should be taking to achieve their goals, but the core competencies that will be required and expected of them upon entering the workforce. The required courses and suggested electives will be cleanly mapped out with respect to the user's desired career and university-specific degree requirements. Each course will have a list of skills the student can expect to develop, as well as a score corresponding to how well the course aligns with the student's desired career.

The purpose of this tool is not to declare with absolution which path the student must follow, but rather, to act as a supplemental resource to provide guidance to those who have a specific career in mind.

Because degree requirements must be manually ingested and validated, only the University of Georgia's Computer Science program is currently supported.

## Current Scope

This project currently treats only the following UGA subjects as in scope:

- CSCI
- MATH
- STAT

Prerequisite references to courses outside those subjects can appear in source catalog text, but they are treated as external or unresolved for this project unless those subjects are intentionally added later.

## Data Pipeline

Run commands from the repository root.

### 1. Ingest Raw Course Catalog Data

The ingestion scripts scrape UGA Bulletin course cards and detail pages into raw JSON files.

```powershell
python pipelines\uga\ingestion\uga_csci_ingest.py
python pipelines\uga\ingestion\uga_math_ingest.py
python pipelines\uga\ingestion\uga_stat_ingest.py
```

Outputs are written to:

```text
data/raw/uga/
```

### 2. Normalize Courses

Combine raw course JSON into a single normalized course catalog.

```powershell
python pipelines\uga\transformation\normalize_courses.py
```

Output:

```text
data/processed/uga/courses/courses_normalized.json
```

### 3. Extract Course Names By Subject

Build a compact subject-grouped course-name file.

```powershell
python pipelines\uga\transformation\course_names.py
```

Output:

```text
data/processed/uga/courses/course_names_by_subject.json
```

### 4. Parse Prerequisites

Transform prerequisite text from normalized course records into parsed groups, items, audit records, and rule objects.

```powershell
python pipelines\uga\transformation\transform_catalog.py
python pipelines\uga\transformation\prerequisite_rules.py
```

Outputs:

```text
data/processed/uga/prerequisites/prerequisite_groups.json
data/processed/uga/prerequisites/prerequisite_items.json
data/processed/uga/prerequisites/prerequisite_parse_audit.json
data/processed/uga/prerequisites/prerequisite_rules.json
```

The prerequisite rules layer supports:

- Empty prerequisite values
- Simple string prerequisites
- Array prerequisite inputs
- Structured prerequisite objects
- `all_of` rules
- `one_of` rules
- Manual-review markers
- Non-course requirements such as department permission
- Minimum grade notes when present
- Co-requisite notes when present

### 5. Build Prerequisite Edges

Build directed prerequisite graph edges from parsed prerequisite rules.

```powershell
python pipelines\uga\transformation\build_prerequisite_edges.py
```

Output:

```text
data/processed/uga/prerequisites/prerequisite_edges.json
```

### 6. Normalize Degree Requirements

Generate normalized UGA degree requirement data.

```powershell
python pipelines\uga\transformation\degree_requirements.py
```

Output:

```text
data/processed/uga/degree_requirements/degree_requirements_normalized.json
```

### 7. Expand Degree Requirements

Resolve course filters into concrete CSCI, MATH, and STAT course lists while preserving exclusions, overlap rules, and notes.

```powershell
python pipelines\uga\transformation\expand_requirement_groups.py
```

Output:

```text
data/processed/uga/degree_requirements/degree_requirements_expanded.json
```

### 8. Build Curriculum Graph

Combine normalized courses, prerequisite edges, and expanded degree requirements into one graph artifact.

```powershell
python pipelines\uga\transformation\build_curriculum_graph.py
```

Output:

```text
data/processed/uga/curriculum_graph/curriculum_graph.json
```

### 9. Validate Curriculum Inputs

Validate normalized courses and degree requirements together.

```powershell
python pipelines\validation\validate_curriculum_inputs.py
```

Default output:

```text
data/processed/uga/validation/curriculum_input_validation_report.json
```

Use strict mode when unresolved prerequisite references should make validation fail:

```powershell
python pipelines\validation\validate_curriculum_inputs.py --strict
```

Because this project is scoped to CSCI, MATH, and STAT, unresolved prerequisite references to other subjects are expected unless the project scope changes.

## Project To-Do List

The full task tracker is kept in:

```text
docs/project_task_list.md
```

Current build order:

- [x] Validate curriculum inputs.
- [x] Normalize prerequisites.
- [x] Build prerequisite edges.
- [x] Expand degree requirements.
- [x] Build curriculum graph.
- [ ] Generate basic course order.
- [ ] Resolve degree requirements.
- [ ] Add completed-courses support.
- [ ] Define skill taxonomy.
- [ ] Extract course skills.
- [ ] Define career tracks.
- [ ] Score career alignment.
- [ ] Generate career-aligned plan.
- [ ] Build API.
- [ ] Build frontend.
- [ ] Add tests.
- [ ] Add documentation.
- [ ] Add demo polish.

MVP target:

Given completed courses such as:

```json
{
  "completed_courses": ["CSCI 1301", "CSCI 1302", "MATH 2250"]
}
```

Return:

- Remaining required courses
- Currently unlocked courses
- Blocked courses
- Missing prerequisites
- Ordered dependency levels
- Requirement satisfaction status
