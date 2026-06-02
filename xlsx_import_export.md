# XLSX Import/Export Plan

## Goal

Add a strict XLSX serialization/deserialization layer for population datasets. One workbook represents exactly one study and must contain enough question-item metadata to preserve scales, options, roles, response links, and respondent data.

## Workbook Contract

Required sheets:

- `study`: study-level metadata as `field | value` rows.
- `questions`: one row per response column/question item.
- `responses`: one row per person, with `person_id` plus one column per question code.

Optional sheets:

- `options`: one row per answer option or scale point.
- Later: `attributes`, `weights`, or `metadata` if needed.

Rules:

- One workbook = one study.
- `responses.person_id` is the respondent identifier and is not imported as a question.
- Every response column except `person_id` must exist in `questions.code`.
- Every `options.question_code` must exist in `questions.code`.
- Question codes must be unique.
- Person IDs must be unique.
- Enum fields must map to DB/Pydantic values: `data_kind`, `role`.
- Categorical/ordinal/binary response values should be checked against options when options are provided.

## Pydantic Boundary

Create a pure XLSX layer:

```python
read_population_xlsx(path: Path) -> PopulationDataset
write_population_xlsx(dataset: PopulationDataset, path: Path) -> None
validate_population_dataset(dataset: PopulationDataset) -> list[ValidationIssue]
```

Use `population_data.models.PopulationDataset` as the canonical in-memory format.

## Import Flow

1. Read workbook sheets.
2. Parse `study` into `Study`.
3. Parse `questions` into Pydantic question models.
4. Parse `options` into `Scale.options`.
5. Parse `responses` into `Person` and `Response` objects.
6. Validate the full `PopulationDataset`.
7. Import the dataset into DB rows using external IDs.
8. Show a preview/conflict dialog before writing when run from UI.

Conflict handling:

- Default: skip existing external IDs.
- UI choices later: skip existing, update existing, replace study contents, import as copy.

## Export Flow

1. User opens export dialog.
2. User selects exactly one study for XLSX export.
3. DB rows are serialized to `PopulationDataset`.
4. Dataset is written to XLSX sheets:
   - `study`
   - `questions`
   - `options`
   - `responses`
5. User downloads the workbook.

For multi-study exports, keep JSON export as the first supported format. XLSX stays one study per workbook.

## DB Mapping

Study:

- `Study.id` -> `PopulationStudyRecord.external_id`
- `Study.name`, source fields, description, metadata map directly.

Question:

- `Question.id` -> `PopulationQuestionRecord.external_id`
- `Question.study_id` -> study external ID
- `Question.source` -> `PopulationSourceRefRecord`
- `Question.scale` -> `PopulationQuestionScaleRecord`
- `Question.scale.options` -> `PopulationQuestionOptionRecord`
- Remaining fields map to kind, role, wording, short name, constructs, missing codes, reverse scoring, harmonized variable, metadata.

Person/response:

- `Person.id` -> `PopulationPersonRecord.external_id`
- `Person.study_id` -> study external ID
- `Person.responses[*].question_id` -> question external ID
- Response values map through `PopulationValueColumns`.

## Implementation Steps

1. Add `services/population_xlsx_serialization_service.py`.
2. Implement workbook reader for `study`, `questions`, `options`, `responses`.
3. Implement workbook writer from `PopulationDataset`.
4. Add validation result dataclasses.
5. Add unit tests with a tiny complete workbook.
6. Add DB import helper that consumes `PopulationDataset`.
7. Add UI import preview/conflict dialog.
8. Add UI XLSX export for one selected study.
9. Update user-facing docs after behavior is implemented and tested.

## Test Cases

- Valid minimal workbook imports to one study, questions, people, responses, scales, and options.
- Exported workbook can be read back into an equivalent `PopulationDataset`.
- Missing required sheets fail validation.
- Response column missing from `questions` fails validation.
- Option row for unknown question fails validation.
- Duplicate question code fails validation.
- Duplicate person ID fails validation.
- Invalid `data_kind` or `role` fails validation.
- Re-import with skip-existing is idempotent.

## Implementation Log

- `bc125de` `Add strict population XLSX serialization`
  - Added `services/population_xlsx_serialization_service.py`.
  - Implemented strict one-study XLSX reading for `study`, `questions`, optional `options`, and `responses`.
  - Implemented XLSX writing from `PopulationDataset`.
  - Added dataset validation for one-study shape, duplicate question/person IDs, response/question links, and option-backed response values.
  - Verified the strict example workbook reads and round-trips through the writer.
- `bbdb3bb` `Test strict population XLSX serialization`
  - Added `tests/test_population_xlsx_serialization.py`.
  - Covered valid strict workbook parsing, XLSX round-trip, missing sheets, unknown response columns, unknown option question codes, duplicate question codes, duplicate person IDs, and invalid `data_kind`.
  - Tightened reader validation so `options.question_code` values must refer to known questions.
  - Verified with `unittest` for the new XLSX tests and existing population integration tests.
- `e45c82a` `Add strict XLSX DB import helpers`
  - Added `PopulationDataset` -> DB import helpers with skip-existing behavior.
  - Added XLSX DB wrappers for importing a strict workbook and exporting one DB study.
  - Covered DB persistence, idempotent re-import, and DB-backed XLSX export in tests.
  - Verified with `unittest` for the XLSX tests and existing population integration tests.
