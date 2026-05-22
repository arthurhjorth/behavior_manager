# Full Population Data Integration

## Summary

Integrate the `population_data` prototype as a first-class module inside the existing Behavior Manager server.

The integrated module will:

- Expose separate routed UI pages under the existing NiceGUI server.
- Replace all runtime file-backed population data, matching configs, notes, audits, and matching runs with DB-backed storage.
- Use dedicated population-domain tables rather than overloading existing `Study` or `DatasetRecord` tables.
- Preserve full prototype UI capability: population/study browsing, question browsing, workspace config, variable mappings, batch matching, individual matching, estimation/validation, and notes.
- Support future DB-backed `.xlsx` imports through the UI and a one-time importer for the current prototype artifacts.

## Key Changes

### Population Module Structure

Create a dedicated population feature area with its own:

- ORM models/tables
- repositories
- services
- UI pages
- import/migration utilities

Do not merge the prototype `app.py` wholesale into `server.py`. Refactor its logic into the existing architecture:

- page registration under the existing server
- reusable population store/query services backed by SQLModel sessions
- matching services independent from UI state
- import services separated from browsing/matching services

Suggested route family:

- `/population`
- `/population/studies`
- `/population/studies/{study_id}`
- `/population/questions`
- `/population/workspaces`
- `/population/workspaces/{workspace_id}/mappings`
- `/population/workspaces/{workspace_id}/matching`
- `/population/workspaces/{workspace_id}/individual-match`
- `/population/workspaces/{workspace_id}/estimate`
- `/population/workspaces/{workspace_id}/notes`
- `/population/import`

Add navigation entry points from the existing shell without changing existing Decisions, Studies, Datasets, NetLogo, or Variables behavior.

### DB Model Migration

Use dedicated SQLModel tables for the complete population/matching domain.

Population data tables should cover:

- source artifacts stored in DB as uploaded binary content plus filename, media type, fingerprint, size, and import metadata
- population studies with stable external prototype IDs and source artifact linkage
- source references for workbook/sheet/row/column provenance
- questions with kind, role, wording, short name, constructs, missing codes, reverse-score flag, metadata, harmonized-variable reference
- question scale/options
- people/respondents with stable external IDs, source person ID, source reference, metadata, and weights
- response values with typed value representation and missing flag
- person responses linking people to questions
- person attributes represented explicitly rather than only as arbitrary JSON blobs

Matching tables should cover:

- workspaces/configurations
- workspace study pairs and primary source/target selection
- matching defaults and diagnostics settings
- variable-set mappings
- mapping inputs for left/right study sides
- transform specs and comparator specs
- fully normalized parameter rows for transform/comparator parameter structures, including nested recode maps, intervals, and weighted component structures
- notes
- audit events
- matching runs
- person matches
- feature-distance rows per match

Keep `custom/manual` transform and comparator kinds as saved placeholders in the schema/UI. Do not add execution hooks now; preserve current runtime semantics.

### Import and Migration Flows

Implement two DB ingestion paths.

1. One-time prototype migration importer:

- Import current `population_data/outputs/population_data.json` into population tables.
- Import current matching config JSON files into workspace/mapping/spec/note/audit tables.
- Import current matching run JSON files into run/match/feature-distance tables.
- Import referenced current raw source files into DB artifact rows when the files are available.
- Preserve stable prototype IDs in external-id columns so configs/runs/questions/people remain linkable and importer reruns can detect already-imported data.

2. Future UI import flow:

- Accept `.xlsx` data workbooks and `.xlsx` question catalogs with parity to current builder behavior.
- Store uploaded source artifacts in the DB.
- Normalize imported studies/questions/people/responses into DB tables.
- Keep normalized population data read-only after import in this integration.
- Use temporary upload files only during parsing; no runtime population state may depend on files in `population_data/outputs` or raw upload folders.

Out of scope for this integration:

- `.sav` ingestion
- `.docx` ingestion
- manual CRUD editing of imported people/questions/responses
- replacing existing generic Dataset import pages

### Matching and UI Behavior

Port the prototype behavior into page-backed workflows.

Population browsing:

- Study/population summaries with person and question counts
- Person inspection and response browsing
- Question browsing/filtering by study

Workspace and mapping workflows:

- Create/select workspace for two studies
- Add variable-set mappings with multiple left/right inputs
- Configure transforms, comparator, output kind, weight, status, notes
- Disable mappings
- Save audit events for meaningful workspace changes

Matching workflows:

- Batch weighted k-NN matching runs remain synchronous with source-person limit controls.
- Persist full run details.
- Individual live matching remains non-persisted unless the prototype already saves a run explicitly.
- Estimation and validation pages preserve current nearest-neighbor estimate behavior and held-out validation behavior.
- Notes remain workspace-scoped DB records.

The matching service should load the needed selected-study people/questions/responses from DB for each operation rather than relying on a global file-backed in-memory store. Preserve current comparison and transform semantics while moving them out of UI code.

## Public Interfaces and Types

Add DB-backed service interfaces for:

- importing population artifacts/workbooks
- querying studies, questions, people, responses
- creating/updating workspaces and mappings
- executing matching runs
- executing individual matching and estimation/validation

Preserve semantic equivalents of the prototype domain types:

- data kinds, question roles, value kinds
- transform kinds
- comparator kinds
- mapping statuses
- matching method/replacement/missing-policy enums
- comparable output kinds

Avoid naming collisions with existing top-level `models.py` concepts by using population-prefixed ORM record names and population-scoped modules.

## Test Plan

### Migration and Import

- One-time importer loads current population JSON into DB with expected counts for studies, questions, and people.
- Importer preserves stable IDs and can rerun without duplicating imported entities.
- Matching config importer reconstructs mappings, transforms, comparators, notes, and audit rows.
- Matching run importer reconstructs run summaries, person matches, and feature-distance rows.
- Source artifact import stores bytes and metadata in DB.
- UI `.xlsx` import handles normal workbooks, question catalogs, empty or invalid workbooks, duplicate/reimport behavior, and provenance fields.

### Matching Semantics

- Transform tests for current supported transform kinds.
- Comparator tests for current supported comparator kinds.
- Distance aggregation matches prototype behavior for missing values and weights.
- Batch weighted k-NN result matches a fixed prototype fixture.
- Individual matching returns nearest neighbors for a fixed workspace fixture.
- Estimation uses weighted mean for numeric/ordinal/Likert targets and weighted vote/summary for categorical behavior.
- Validation holdout path excludes the held-out mapping correctly.

### UI and Integration

- Existing server starts with population pages registered.
- Navigation reaches population pages without breaking current existing pages.
- Population browse pages work from DB with no `population_data.json` runtime dependency.
- Workspace mapping forms persist DB rows.
- Batch matching persists a run and reloads its detail view.
- Notes persist and display.
- No population config/run/source data is required from file-backed output directories after migration.

## Assumptions

- Use dedicated population tables; do not force population data into existing generic Dataset tables or current PDF-oriented Study rows.
- Raw source artifacts are DB-backed after import.
- Imported normalized population data is read-only in this integration.
- Future import support is `.xlsx` parity only.
- Matching configuration internals are fully normalized with parameter child rows rather than whole-config JSON blobs.
- Matching runs persist full detail.
- Matching execution remains synchronous for parity with the prototype and current source-person limit controls.
- `custom/manual` transform and comparator options remain labeled placeholders, not executable plugin hooks.

## Implementation Steps

1. Add population ORM foundations.
   - Add population-specific enums and SQLModel tables for artifacts, studies, questions, people, responses, source refs, scales/options, attributes, and weights.
   - Commit: `574df51` `Add population data ORM models`.
2. Add matching ORM foundations.
   - Add workspace/config, mapping, mapping-input, transform/comparator spec, normalized parameter, notes, audit, run, match, and feature-distance tables.
   - Commit: `4850da9` `Add population matching ORM models`.
3. Add population repositories.
   - Add DB query/write helpers for population artifacts, studies, questions, people, and responses.
   - Commit: `b423bea` `Add population data repositories`.
4. Add DB-backed XLSX import service.
   - Refactor prototype ingestion behavior into services that normalize uploaded `.xlsx` workbooks and question catalogs into DB rows and store source artifacts in DB.
   - Commit: `accb050` `Add population workbook import services`.
5. Add one-time prototype migration importer.
   - Import current population JSON, config JSON, run JSON, and available raw source files into DB while preserving prototype external IDs and rerun safety.
   - Commit: `56ee702` `Add population prototype migration service`.
6. Add population browse pages.
   - Register population study, person/response, question, and import pages under existing server navigation.
   - Commit: pending.
7. Add matching repositories and services.
   - Move transform, comparator, distance, matching, estimation, and validation logic into DB-backed matching services.
   - Commit: pending.
8. Add workspace and mapping pages.
   - Port workspace/config selection and variable-set mapping management pages.
   - Commit: pending.
9. Add matching execution pages.
   - Port batch matching, individual matching, estimation, validation, notes, and run-result views while persisting full batch run detail.
   - Commit: pending.
10. Add tests and parity fixtures.
   - Add importer, matching semantic, migration, and UI/server registration tests with small fixtures.
   - Commit: pending.
11. Wire docs and cleanup.
   - Update navigation/docs and remove integrated runtime dependence on prototype file-backed outputs.
   - Commit: pending.
