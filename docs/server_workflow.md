# Server Workflow

The project also includes a GUI server for creating and inspecting the evidence-linked building blocks used by the model.

## What the Server Is For

The server gives you a way to work with the persistent versions of the concepts that appear in the in-memory examples:

- studies
- decisions
- variables
- contexts
- datasets
- adapter sets and their conditions/effects

At a high level, the workflow is:

1. Add studies to the database.
2. Create decisions and outcomes.
3. Define variables and contexts that decisions depend on.
4. Create adapter sets that encode evidence-informed changes to outcome likelihoods.
5. Attach those adapter sets to studies so the evidence source is explicit.
6. Test and export decisions.

## Typical Workflow in the GUI

### 1. Upload Studies

Use the `Studies` page to upload PDF studies. These become database records that can later be referenced by adapter sets.

### 2. Create or Edit Decisions

Use the `Decisions` page to create a decision, define its description, and add outcomes.

### 3. Define Variables and Contexts

Use the `Variables` and `Contexts` pages to define the inputs that decision rules will depend on.

### 4. Add Adapter Sets

Each adapter set describes a rule of the form:

`if <conditions> then <effects>`

Conditions are built from chains and predicates. Effects target one or more outcomes and modify their likelihoods.

### 5. Attach Adapters to Studies

When editing an adapter set, you can assign it to a study in the database. This makes the evidence source visible both on the adapter edit page and on the decision overview pages.

### 6. Test and Export

Decisions can be tested in the GUI and exported to NetLogo-oriented code paths where relevant.

## Related Pages

- `server.py` registers the NiceGUI pages and top-level routes.
- `ui/pages/` contains page-level route handlers.
- `ui/views/` contains reusable UI rendering functions.
