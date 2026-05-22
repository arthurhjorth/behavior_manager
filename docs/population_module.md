# Population Module

The population module brings the separate population-data prototype into the main GUI server as DB-backed pages and services.

## What It Stores

Population data is stored in dedicated database tables, not in `population_data/outputs` at runtime.

The DB stores:

- uploaded source artifacts as bytes plus filename, fingerprint, and metadata
- imported population studies
- questions, scales, people, responses, attributes, and weights
- matching workspaces for two studies
- variable mappings, transforms, comparators, notes, audit events, matching runs, matches, and feature distances

The one-time migration service can read the old prototype files, but the server pages and matching services use DB rows after import.

## Main Pages

- `/population/studies` lists imported population studies.
- `/population/studies/{study_id}` shows study-level questions and people.
- `/population/studies/{study_id}/people/{person_id}` shows one person and their responses.
- `/population/questions` filters questions across imported studies.
- `/population/import` imports `.xlsx` population workbooks and question catalogs.
- `/population/workspaces` creates matching workspaces for two studies.
- `/population/workspaces/{workspace_id}/mappings` defines variable-set mappings between the workspace studies.
- `/population/workspaces/{workspace_id}/matching` runs batch weighted k-NN matching and lists saved runs.
- `/population/workspaces/{workspace_id}/runs/{run_id}` shows persisted run details.
- `/population/workspaces/{workspace_id}/individual-match` runs live non-persisted matching for one source person.
- `/population/workspaces/{workspace_id}/estimate` estimates target-question values from nearest neighbors and runs holdout validation.
- `/population/workspaces/{workspace_id}/notes` stores workspace notes and tags.

## Import Workflow

Use `/population/import` for new `.xlsx` files.

For normal data workbooks, each populated sheet becomes a population study. The first row is treated as question headers. Each subsequent row is treated as one person, and all cell values become typed responses.

For question catalogs, include `question-items` in the filename. These workbooks import question metadata without people or responses.

The importer is rerunnable for the same workbook content and stable study IDs. If an imported study already exists, it is skipped rather than duplicated.

## Matching Workflow

1. Create a workspace under `/population/workspaces` by selecting two imported studies.
2. Add mappings under the workspace mapping page. A mapping selects one or more questions from each study, transforms each side, compares the transformed values, and assigns a weight.
3. Use the batch matching page to persist a weighted k-NN run. The run stores summary data, person matches, ranks, similarities, distances, and per-feature contributions.
4. Use individual matching for quick inspection without saving a run.
5. Use estimate/validate to estimate a target question from neighbors or to hold out a one-to-one mapping and compare estimated vs actual values.

Only approved mappings are used by the matching service. Disabled mappings remain stored for auditability but are ignored.

## Migration Workflow

The migration service is for importing the old prototype once:

```bash
python -m services.population_migration_service population_data
```

It reads prototype JSON outputs and available raw source files, writes normalized records to the Behavior Manager database, and preserves prototype external IDs so reruns can skip already migrated data.
