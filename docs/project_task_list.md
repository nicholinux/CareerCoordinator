# CurriculumGraph AI Project Task List

## Project Goal

Build a web app that uses normalized course data, catalog data, degree requirements, prerequisite logic, and AI-assisted career alignment to recommend the correct order to take BS Computer Science courses.

## Current Scope

This implementation is currently concerned only with UGA courses in:

- CSCI
- MATH
- STAT

Prerequisite references outside those subjects may be reported as unresolved or external unless the project scope changes.

## Non-Goals

- Do not handle semester scheduling.
- Do not handle CRNs.
- Do not handle instructors.
- Do not handle campuses.
- Do not handle meeting times.
- Do not handle seat availability.
- Do not handle catalog year.
- Do not handle when courses are normally offered.

## Existing Inputs

- `data/processed/catalog/courses_normalized.json`
- `data/processed/catalog/course_catalogs.json`
- `data/processed/curriculum/degree_requirements_normalized.json`

## Required Build Order

### 1. Validate Curriculum Inputs

Create:

`pipelines/validation/validate_curriculum_inputs.py`

Tasks:

- [ ] Load `courses_normalized.json`.
- [ ] Load `course_catalogs.json`.
- [ ] Load `degree_requirements_normalized.json`.
- [ ] Normalize course codes.
- [ ] Build course-code lookup.
- [ ] Validate required course fields.
- [ ] Detect duplicate course codes.
- [ ] Validate requirement group structure.
- [ ] Extract all course references from requirements.
- [ ] Check that requirement courses exist in normalized course list.
- [ ] Extract prerequisite references from normalized courses.
- [ ] Report missing prerequisite courses as warnings unless strict mode is enabled.
- [ ] Validate `course_filter` objects.
- [ ] Write report to `data/processed/validation/curriculum_input_validation_report.json`.

### 2. Normalize Prerequisites

Create:

`pipelines/transformation/normalize_prerequisites.py`

Tasks:

- [ ] Load `courses_normalized.json`.
- [ ] Read each course's prerequisite field.
- [ ] Handle empty prerequisites.
- [ ] Parse simple prerequisite strings.
- [ ] Parse prerequisite arrays.
- [ ] Parse structured prerequisite objects.
- [ ] Detect `all_of` prerequisite logic.
- [ ] Detect `one_of` prerequisite logic where possible.
- [ ] Preserve raw prerequisite text.
- [ ] Mark ambiguous prerequisite rules as `manual_review`.
- [ ] Mark permission-only rules as `non_course_requirement`.
- [ ] Write output to `data/processed/curriculum/prerequisite_rules.json`.

### 3. Build Prerequisite Edges

Create:

`pipelines/transformation/build_prerequisite_edges.py`

Tasks:

- [x] Load `prerequisite_rules.json`.
- [x] Extract prerequisite course references.
- [x] Create directed edges from prerequisite course to unlocked course.
- [x] Preserve AND/OR logic metadata.
- [x] Skip non-course requirements.
- [x] Detect self-referential edges.
- [x] Track unresolved prerequisite references.
- [x] Write output to `data/processed/uga/prerequisites/prerequisite_edges.json`.

Edge direction:

`prerequisite_course -> unlocked_course`

### 4. Expand Degree Requirements

Create:

`pipelines/transformation/expand_requirement_groups.py`

Tasks:

- [x] Load `degree_requirements_normalized.json`.
- [x] Load `courses_normalized.json`.
- [x] Preserve `all_of`, `one_of`, `minimum_credits`, and `note` groups.
- [x] Resolve `course_filter` objects into concrete course-code lists.
- [x] Apply subject filters.
- [x] Apply minimum and maximum course-level filters.
- [x] Preserve exclusions.
- [x] Preserve `overlap_allowed`.
- [x] Preserve notes.
- [x] Report empty filters.
- [x] Write output to `data/processed/uga/degree_requirements/degree_requirements_expanded.json`.

### 5. Build Curriculum Graph

Create:

`pipelines/transformation/build_curriculum_graph.py`

Tasks:

- [ ] Load `courses_normalized.json`.
- [ ] Load `prerequisite_rules.json`.
- [ ] Load `prerequisite_edges.json`.
- [ ] Load `degree_requirements_expanded.json`.
- [ ] Create one node per course.
- [ ] Attach course metadata to each node.
- [ ] Attach requirement group IDs to course nodes.
- [ ] Mark required courses.
- [ ] Mark elective candidates.
- [ ] Add prerequisite edges.
- [ ] Add requirement group metadata.
- [ ] Detect prerequisite cycles.
- [ ] Detect isolated courses.
- [ ] Write output to `data/processed/curriculum/curriculum_graph.json`.

### 6. Generate Basic Course Order

Create:

`pipelines/sequencing/generate_course_order.py`

Tasks:

- [ ] Load `curriculum_graph.json`.
- [ ] Accept a target course set.
- [ ] Accept optional completed courses.
- [ ] Treat completed courses as satisfied prerequisites.
- [ ] Perform topological sort.
- [ ] Group courses by prerequisite depth.
- [ ] Identify currently unlocked courses.
- [ ] Identify blocked courses.
- [ ] Show missing prerequisites for blocked courses.
- [ ] Report unresolved prerequisites.
- [ ] Write output to `data/processed/curriculum/recommended_course_order.json`.

Important:

- Order levels are not semesters.
- Same-level courses are only dependency-equivalent.

### 7. Resolve Degree Requirements

Create:

`pipelines/sequencing/resolve_degree_requirements.py`

Tasks:

- [ ] Load `degree_requirements_expanded.json`.
- [ ] Load `curriculum_graph.json`.
- [ ] Include all `all_of` courses.
- [ ] Choose one course for each `one_of` group.
- [ ] Choose enough courses for each `minimum_credits` group.
- [ ] Avoid double-counting unless `overlap_allowed` is true.
- [ ] Apply exclusions.
- [ ] Prefer courses with fewer unmet prerequisites.
- [ ] Prefer lower prerequisite depth.
- [ ] Preserve unselected alternatives.
- [ ] Explain each selected course.
- [ ] Write output to `data/processed/curriculum/selected_degree_plan.json`.

### 8. Add Completed-Courses Support

Create:

`data/input/student_completed_courses.json`

Tasks:

- [ ] Define a `completed_courses` array.
- [ ] Normalize completed course codes.
- [ ] Validate completed courses.
- [ ] Remove completed courses from remaining requirements.
- [ ] Treat completed courses as satisfied prerequisites.
- [ ] Return remaining courses.
- [ ] Return unlocked courses.
- [ ] Return blocked courses.

Example input:

```json
{
  "completed_courses": ["CSCI 1301", "CSCI 1302", "MATH 2250"]
}
```

### 9. Define Skill Taxonomy

Create:

`data/processed/skills/skill_taxonomy.json`

Tasks:

- [ ] Define controlled skill categories.
- [ ] Define skill labels.
- [ ] Define skill aliases.
- [ ] Prevent unlimited AI-generated skills.

Suggested categories:

- Programming
- Algorithms
- Databases
- Data Engineering
- Machine Learning
- Statistics
- Software Engineering
- Systems
- Networks
- Cybersecurity
- Web Development
- Research

### 10. Extract Course Skills

Create:

`pipelines/ml/extract_course_skills.py`

Tasks:

- [ ] Load `courses_normalized.json`.
- [ ] Load `skill_taxonomy.json`.
- [ ] Build course text from title, description, and prerequisites.
- [ ] Extract skills using controlled taxonomy.
- [ ] Include confidence scores.
- [ ] Include evidence text.
- [ ] Reject skills outside taxonomy.
- [ ] Mark low-confidence results for review.
- [ ] Write output to `data/processed/skills/course_skills.json`.

### 11. Define Career Tracks

Create:

`data/processed/skills/career_tracks.json`

Tasks:

- [ ] Define Data Engineering track.
- [ ] Define ML Engineering track.
- [ ] Define Software Engineering track.
- [ ] Define Data Science / Analytics track.
- [ ] Assign weighted skills to each track.

### 12. Score Career Alignment

Create:

`pipelines/ml/score_career_alignment.py`

Tasks:

- [ ] Load `course_skills.json`.
- [ ] Load `career_tracks.json`.
- [ ] Compute weighted skill-match score.
- [ ] Normalize score to 0-1.
- [ ] Store matched skills.
- [ ] Store missing skills.
- [ ] Store explanation.
- [ ] Write output to `data/processed/skills/career_track_scores.json`.

### 13. Generate Career-Aligned Plan

Create:

`pipelines/sequencing/generate_career_aligned_plan.py`

Tasks:

- [ ] Load `selected_degree_plan.json`.
- [ ] Load `curriculum_graph.json`.
- [ ] Load `career_track_scores.json`.
- [ ] Load completed courses if provided.
- [ ] Include all mandatory courses.
- [ ] Choose career-aligned options for `one_of` groups.
- [ ] Choose career-aligned courses for `minimum_credits` groups.
- [ ] Preserve prerequisite validity.
- [ ] Avoid double-counting.
- [ ] Generate ordered course levels.
- [ ] Explain selected electives.
- [ ] Explain skipped alternatives.
- [ ] Show skill coverage before and after plan.
- [ ] Write output to `data/processed/curriculum/career_aligned_course_plan.json`.

### 14. Build API

Location:

`apps/api/`

Tasks:

- [ ] Choose FastAPI or Node/Express.
- [ ] Add health endpoint.
- [ ] Add JSON loading layer.
- [ ] Add request validation.
- [ ] Add response schemas.
- [ ] Add error handling.
- [ ] Add CORS.
- [ ] Add API docs.

Required endpoints:

- [ ] `GET /health`
- [ ] `GET /courses`
- [ ] `GET /courses/{course_code}`
- [ ] `GET /requirements`
- [ ] `GET /graph`
- [ ] `GET /graph/course/{course_code}`
- [ ] `POST /plan/basic`
- [ ] `POST /plan/career-aligned`
- [ ] `POST /plan/validate-completed-courses`
- [ ] `GET /skills/courses/{course_code}`
- [ ] `GET /skills/career-tracks`
- [ ] `GET /pipeline/validation-report`

### 15. Build Frontend

Location:

`apps/web/`

Main user story:

A student enters completed courses, chooses a career track, and receives a prerequisite-aware course sequence with explanations.

Pages:

- [ ] Landing / overview page
- [ ] Course Explorer
- [ ] Course Detail
- [ ] Degree Requirements
- [ ] Curriculum Graph
- [ ] Plan Generator
- [ ] Career Alignment
- [ ] Pipeline Status

Course Explorer:

- [ ] Search by course code.
- [ ] Search by title.
- [ ] Filter by subject.
- [ ] Filter by level.
- [ ] Show title, credits, description preview.
- [ ] Show prerequisite count.
- [ ] Show requirement badges.

Course Detail:

- [ ] Show course metadata.
- [ ] Show prerequisites.
- [ ] Show raw prerequisite text.
- [ ] Show unlocked courses.
- [ ] Show requirement groups.
- [ ] Show skills.
- [ ] Show career scores.
- [ ] Show parse warnings.

Degree Requirements:

- [ ] Show each requirement group.
- [ ] Show group type.
- [ ] Show required courses.
- [ ] Show alternatives.
- [ ] Show credit minimums.
- [ ] Show exclusions.
- [ ] Show overlap rules.

Curriculum Graph:

- [ ] Visualize prerequisite graph.
- [ ] Click course nodes.
- [ ] Highlight prerequisites.
- [ ] Highlight unlocked courses.
- [ ] Show cycles.
- [ ] Distinguish required courses from electives.

Plan Generator:

- [ ] Completed-course selector.
- [ ] Career-track selector.
- [ ] Generate plan button.
- [ ] Display ordered course levels.
- [ ] Display unlocked courses.
- [ ] Display blocked courses.
- [ ] Display missing prerequisites.
- [ ] Display requirement satisfaction.
- [ ] Display selected electives.
- [ ] Display skipped alternatives.
- [ ] Explain decisions.

Career Alignment:

- [ ] Show career tracks.
- [ ] Show skill weights.
- [ ] Show course relevance scores.
- [ ] Show completed-course skill coverage.
- [ ] Show recommended-plan skill coverage.
- [ ] Show missing skills.
- [ ] Show courses that improve missing skills.

Pipeline Status:

- [ ] Show validation report.
- [ ] Show course count.
- [ ] Show requirement group count.
- [ ] Show missing requirement courses.
- [ ] Show missing prerequisite courses.
- [ ] Show duplicates.
- [ ] Show invalid groups.
- [ ] Show graph edge count.
- [ ] Show cycle count.

### 16. Add Tests

Pipeline tests:

- [ ] Course-code normalization
- [ ] Requirement course extraction
- [ ] Prerequisite extraction
- [ ] Course filter resolution
- [ ] Duplicate detection
- [ ] Edge creation
- [ ] Cycle detection
- [ ] Topological sort
- [ ] Completed-course filtering
- [ ] Requirement resolver
- [ ] Career scoring

API tests:

- [ ] `/health`
- [ ] `/courses`
- [ ] `/courses/{course_code}`
- [ ] `/requirements`
- [ ] `/plan/basic`
- [ ] `/plan/career-aligned`
- [ ] Invalid course input
- [ ] Invalid completed-course input
- [ ] Invalid career track input

Frontend tests:

- [ ] Course search
- [ ] Completed-course selector
- [ ] Plan generation
- [ ] Empty states
- [ ] Loading states
- [ ] Invalid input display
- [ ] Blocked course display
- [ ] Requirement group rendering

### 17. Add Documentation

README tasks:

- [ ] Title
- [ ] One-sentence summary
- [ ] Problem statement
- [ ] What the app does
- [ ] What the app does not do
- [ ] Architecture diagram
- [ ] Data pipeline overview
- [ ] JSON input descriptions
- [ ] Curriculum graph explanation
- [ ] Sequencing algorithm explanation
- [ ] AI skill extraction explanation
- [ ] Career scoring explanation
- [ ] Screenshots
- [ ] Setup instructions
- [ ] Demo instructions
- [ ] Known limitations
- [ ] Future work

Docs to create:

- [ ] `docs/data_dictionary.md`
- [ ] `docs/requirement_logic.md`
- [ ] `docs/prerequisite_parsing.md`
- [ ] `docs/curriculum_graph.md`
- [ ] `docs/sequencing_algorithm.md`
- [ ] `docs/career_scoring.md`
- [ ] `docs/api_reference.md`

### 18. Demo Polish

Tasks:

- [ ] Create sample completed-courses profile.
- [ ] Create Data Engineering demo plan.
- [ ] Create ML Engineering demo plan.
- [ ] Create Software Engineering demo plan.
- [ ] Add screenshots.
- [ ] Record short demo video.
- [ ] Add demo GIF if possible.

## MVP Milestone

Before building AI, frontend polish, or database support, the system must do this:

Given:

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
