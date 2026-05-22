from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO, StringIO
from pathlib import Path
import csv
import re
import zipfile

from sqlmodel import Session, select

from models import PopulationPersonRecord, PopulationQuestionRecord, PopulationResponseRecord, PopulationStudyRecord
from netlogo_ast.main import extract_code_section, parse_model_text, replace_code_section, upsert_procedures_in_model_text
from repositories import population_repo


DATA_FILENAME = "population_data.csv"
README_FILENAME = "README.md"
PROCEDURE_NAME = "setup-population-from-dataset"


@dataclass(frozen=True)
class PopulationFieldMapping:
    question_id: int
    source_name: str
    netlogo_name: str


@dataclass(frozen=True)
class NetLogoPopulationPackage:
    filename: str
    content: bytes
    field_mappings: list[PopulationFieldMapping]
    row_count: int


def breed_options(model_text: str) -> dict[str, str]:
    program = parse_model_text(model_text)
    options = {"turtles": "turtles"}
    for declaration in program.declarations:
        if declaration.kind.lower() == "breed" and len(declaration.values) >= 2:
            plural = str(declaration.values[0])
            singular = str(declaration.values[1])
            options[plural] = f"{plural} ({singular})"
    return options


def build_population_package(
    session: Session,
    *,
    model_text: str,
    model_filename: str,
    study_id: int,
    question_ids: list[int],
    agent_kind: str,
) -> NetLogoPopulationPackage:
    if not question_ids:
        raise ValueError("Choose at least one population field.")
    study = session.get(PopulationStudyRecord, study_id)
    if study is None:
        raise ValueError("Population study not found.")
    question_rows = _selected_questions(session, study_id, question_ids)
    if len(question_rows) != len(set(question_ids)):
        raise ValueError("One or more selected fields do not belong to the selected population study.")

    valid_agents = breed_options(model_text)
    if agent_kind not in valid_agents:
        raise ValueError("Choose turtles or one of the breeds declared in the selected model.")

    mappings = _field_mappings(question_rows)
    csv_text, row_count = _population_csv(session, study_id, mappings)
    generated_model = inject_population_setup(model_text, agent_kind=agent_kind, variable_names=[item.netlogo_name for item in mappings])
    zip_content = _zip_package(
        model_filename=model_filename,
        model_text=generated_model,
        csv_text=csv_text,
        readme_text=_readme(study.name, model_filename, agent_kind, mappings, row_count),
    )
    suffix = Path(model_filename).suffix or ".nlogo"
    filename = f"{Path(model_filename).stem}_population_package.zip"
    return NetLogoPopulationPackage(filename=filename, content=zip_content, field_mappings=mappings, row_count=row_count)


def inject_population_setup(model_text: str, *, agent_kind: str, variable_names: list[str]) -> str:
    code = extract_code_section(model_text)
    code = _ensure_csv_extension(code)
    owner_declaration = "turtles-own" if agent_kind == "turtles" else f"{agent_kind}-own"
    code = _ensure_own_variables(code, owner_declaration, variable_names)
    updated = replace_code_section(model_text, code)
    return upsert_procedures_in_model_text(
        updated,
        {
            PROCEDURE_NAME: _population_setup_procedure(agent_kind, variable_names),
        },
    )


def safe_netlogo_name(value: str) -> str:
    text = re.sub(r"[^a-z0-9_\-\?\!]+", "-", value.strip().lower())
    text = re.sub(r"-+", "-", text).strip("-_")
    if not text:
        text = "field"
    if text[0].isdigit():
        text = f"field-{text}"
    return text


def _selected_questions(session: Session, study_id: int, question_ids: list[int]) -> list[PopulationQuestionRecord]:
    order = {question_id: index for index, question_id in enumerate(question_ids)}
    rows = list(
        session.exec(
            select(PopulationQuestionRecord)
            .where(PopulationQuestionRecord.study_id == study_id)
            .where(PopulationQuestionRecord.id.in_(question_ids))
        )
    )
    return sorted(rows, key=lambda row: order.get(int(row.id), 0))


def _field_mappings(questions: list[PopulationQuestionRecord]) -> list[PopulationFieldMapping]:
    used: set[str] = set()
    mappings: list[PopulationFieldMapping] = []
    for question in questions:
        source_name = question.short_name or question.wording
        base_name = safe_netlogo_name(source_name)
        name = base_name
        suffix = 2
        while name in used:
            name = f"{base_name}-{suffix}"
            suffix += 1
        used.add(name)
        mappings.append(
            PopulationFieldMapping(
                question_id=int(question.id),
                source_name=source_name,
                netlogo_name=name,
            )
        )
    return mappings


def _population_csv(
    session: Session,
    study_id: int,
    mappings: list[PopulationFieldMapping],
) -> tuple[str, int]:
    people = list(
        session.exec(
            select(PopulationPersonRecord)
            .where(PopulationPersonRecord.study_id == study_id)
            .order_by(PopulationPersonRecord.id)
        )
    )
    question_ids = [mapping.question_id for mapping in mappings]
    response_rows = list(
        session.exec(
            select(PopulationResponseRecord)
            .where(PopulationResponseRecord.question_id.in_(question_ids))
        )
    )
    values = {
        (response.person_id, response.question_id): "" if response.is_missing else population_repo.json_load(response.normalized_json, "")
        for response in response_rows
    }

    output = StringIO()
    writer = csv.writer(output)
    writer.writerow([mapping.netlogo_name for mapping in mappings])
    for person in people:
        writer.writerow([values.get((int(person.id), mapping.question_id), "") for mapping in mappings])
    return output.getvalue(), len(people)


def _ensure_csv_extension(code: str) -> str:
    pattern = re.compile(r"(?ims)^(\s*extensions\s*\[)(.*?)(\]\s*)$")
    match = pattern.search(code)
    if match:
        extensions = match.group(2).split()
        if any(extension.lower() == "csv" for extension in extensions):
            return code
        return pattern.sub(lambda item: f"{item.group(1)}{item.group(2).rstrip()} csv{item.group(3)}", code, count=1)
    return "extensions [csv]\n" + code.lstrip()


def _ensure_own_variables(code: str, declaration_name: str, variable_names: list[str]) -> str:
    pattern = re.compile(rf"(?ims)^(\s*{re.escape(declaration_name)}\s*\[)(.*?)(\]\s*)$")
    match = pattern.search(code)
    if match:
        existing = match.group(2).split()
        existing_lower = {value.lower() for value in existing}
        additions = [value for value in variable_names if value.lower() not in existing_lower]
        if not additions:
            return code

        def replace(item: re.Match[str]) -> str:
            values = " ".join(existing + additions)
            return f"{item.group(1)} {values} {item.group(3)}"

        return pattern.sub(replace, code, count=1)
    declaration = f"{declaration_name} [ {' '.join(variable_names)} ]\n"
    return _insert_before_first_procedure(code, declaration)


def _insert_before_first_procedure(code: str, insertion: str) -> str:
    pattern = re.compile(r"(?im)^\s*to(?:-report)?\s+")
    match = pattern.search(code)
    if match:
        return code[: match.start()] + insertion + code[match.start():]
    return code.rstrip() + "\n" + insertion


def _population_setup_procedure(agent_kind: str, variable_names: list[str]) -> str:
    create_command = "create-turtles" if agent_kind == "turtles" else f"create-{agent_kind}"
    assignments = "\n".join(
        f"      set {name} item {index} bm-row"
        for index, name in enumerate(variable_names)
    )
    return f"""to {PROCEDURE_NAME}
  let bm-population-rows csv:from-file "{DATA_FILENAME}"
  if empty? bm-population-rows [ stop ]
  foreach but-first bm-population-rows [ bm-row ->
    {create_command} 1 [
{assignments}
    ]
  ]
end"""


def _zip_package(*, model_filename: str, model_text: str, csv_text: str, readme_text: str) -> bytes:
    output = BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as package:
        package.writestr(Path(model_filename).name, model_text)
        package.writestr(DATA_FILENAME, csv_text)
        package.writestr(README_FILENAME, readme_text)
    return output.getvalue()


def _readme(
    study_name: str,
    model_filename: str,
    agent_kind: str,
    mappings: list[PopulationFieldMapping],
    row_count: int,
) -> str:
    mapping_lines = "\n".join(f"- `{item.source_name}` -> `{item.netlogo_name}`" for item in mappings)
    return f"""# NetLogo Population Package

Generated from population study `{study_name}` for model `{model_filename}`.

## Contents

- `{Path(model_filename).name}`: model with CSV support, owned variables, and `{PROCEDURE_NAME}`.
- `{DATA_FILENAME}`: selected population fields, one row per population person.
- `{README_FILENAME}`: this file.

## How To Use

Keep `{DATA_FILENAME}` next to the model file so NetLogo can read it.

Run:

```netlogo
{PROCEDURE_NAME}
```

The procedure creates one `{agent_kind}` agent for each CSV row and assigns the selected fields to that agent.

Rows exported: {row_count}

## Field Mapping

{mapping_lines}
"""
