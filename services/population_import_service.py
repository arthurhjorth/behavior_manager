from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import date, datetime
from io import BytesIO
from typing import Any

import openpyxl
from sqlmodel import Session

from models import (
    PopulationDataKind,
    PopulationPersonAttributeRecord,
    PopulationPersonRecord,
    PopulationQuestionRecord,
    PopulationQuestionRole,
    PopulationResponseRecord,
    PopulationValueKind,
)
from repositories import population_repo


QUESTION_CATALOG_MARKER = "question-items"


@dataclass(frozen=True)
class PopulationImportResult:
    artifact_id: int
    study_ids: list[int]
    study_count: int
    question_count: int
    person_count: int


def import_workbook_bytes(
    session: Session,
    *,
    filename: str,
    content: bytes,
    media_type: str = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
) -> PopulationImportResult:
    fingerprint = hashlib.sha256(content).hexdigest()
    artifact = population_repo.get_artifact_by_fingerprint(session, fingerprint)
    if artifact is None:
        artifact = population_repo.create_artifact(
            session,
            filename=filename,
            media_type=media_type,
            fingerprint=fingerprint,
            content=content,
            metadata={"import_kind": "population_xlsx"},
        )

    workbook = openpyxl.load_workbook(BytesIO(content), read_only=True, data_only=True)
    if QUESTION_CATALOG_MARKER in filename.lower():
        studies, question_count = _import_question_catalog(session, workbook, filename, int(artifact.id))
        person_count = 0
    else:
        studies, question_count, person_count = _import_data_workbook(session, workbook, filename, int(artifact.id))
    session.commit()
    return PopulationImportResult(
        artifact_id=int(artifact.id),
        study_ids=[int(study.id) for study in studies if study.id is not None],
        study_count=len(studies),
        question_count=question_count,
        person_count=person_count,
    )


def slugify(value: str, max_length: int = 80) -> str:
    compact = re.sub(r"[^a-z0-9]+", "_", value.strip().lower())
    compact = re.sub(r"_+", "_", compact).strip("_")
    return (compact[:max_length].strip("_") or "item")


def compact_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value)).strip()


def jsonable(value: Any) -> Any:
    if isinstance(value, datetime | date):
        return value.isoformat()
    return value


def value_columns(value: Any) -> dict[str, Any]:
    if value is None:
        return _value_columns(PopulationValueKind.missing, None, None, True)
    if isinstance(value, bool):
        return _value_columns(PopulationValueKind.boolean, value, value)
    if isinstance(value, int):
        return _value_columns(PopulationValueKind.integer, value, value)
    if isinstance(value, float):
        return _value_columns(PopulationValueKind.number, value, value)
    if isinstance(value, datetime):
        normalized = value.isoformat()
        return _value_columns(PopulationValueKind.datetime, normalized, normalized)
    if isinstance(value, date):
        normalized = value.isoformat()
        return _value_columns(PopulationValueKind.date, normalized, normalized)
    text = compact_text(value)
    if not text:
        return _value_columns(PopulationValueKind.missing, "", None, True)
    return _value_columns(PopulationValueKind.string, text, text)


def _value_columns(kind: PopulationValueKind, raw: Any, normalized: Any, missing: bool = False) -> dict[str, Any]:
    return {
        "value_kind": kind,
        "raw_json": population_repo.json_dump(jsonable(raw)),
        "normalized_json": population_repo.json_dump(jsonable(normalized)),
        "is_missing": missing,
    }


def _sheet_rows(worksheet: Any) -> list[tuple[Any, ...]]:
    return [row for row in worksheet.iter_rows(values_only=True) if any(cell is not None for cell in row)]


def _import_data_workbook(
    session: Session,
    workbook: Any,
    filename: str,
    artifact_id: int,
) -> tuple[list[Any], int, int]:
    studies = []
    question_count = 0
    person_count = 0
    for worksheet in workbook.worksheets:
        rows = _sheet_rows(worksheet)
        if len(rows) < 2:
            continue
        headers = [compact_text(value) if value is not None else "" for value in rows[0]]
        if not any(headers):
            continue
        external_study_id = _study_id(filename, worksheet.title)
        if population_repo.get_study_by_external_id(session, external_study_id) is not None:
            continue
        study = population_repo.create_study(
            session,
            external_id=external_study_id,
            name=worksheet.title,
            source_file=filename,
            source_sheet=worksheet.title,
            source_artifact_id=artifact_id,
            metadata={"row_count": len(rows) - 1, "column_count": len(headers)},
        )
        studies.append(study)
        questions_by_column: dict[int, PopulationQuestionRecord] = {}
        for column_index, header in enumerate(headers, start=1):
            if not header:
                continue
            values = [row[column_index - 1] if column_index - 1 < len(row) else None for row in rows[1:]]
            source_ref = population_repo.create_source_ref(
                session,
                file_path=filename,
                sheet_name=worksheet.title,
                row_index=1,
                column_index=column_index,
                column_name=header,
            )
            scale = _scale_for_values(session, values)
            question = population_repo.create_question(
                session,
                PopulationQuestionRecord(
                    external_id=_question_id(external_study_id, column_index, header),
                    study_id=int(study.id),
                    source_ref_id=int(source_ref.id),
                    scale_id=int(scale.id) if scale else None,
                    kind=_question_kind(header, values),
                    wording=header,
                    short_name=header,
                    role=_question_role(header),
                    constructs_json=population_repo.json_dump(_constructs(header)),
                ),
            )
            questions_by_column[column_index] = question
            question_count += 1

        for row_index, row in enumerate(rows[1:], start=2):
            person_source = population_repo.create_source_ref(
                session,
                file_path=filename,
                sheet_name=worksheet.title,
                row_index=row_index,
            )
            person = population_repo.create_person(
                session,
                PopulationPersonRecord(
                    external_id=f"{external_study_id}__person_{row_index - 1:05d}",
                    study_id=int(study.id),
                    source_ref_id=int(person_source.id),
                    source_person_id=str(jsonable(row[0])) if row and row[0] is not None else None,
                ),
            )
            person_count += 1
            for column_index, question in questions_by_column.items():
                header = headers[column_index - 1]
                raw = row[column_index - 1] if column_index - 1 < len(row) else None
                source_ref = population_repo.create_source_ref(
                    session,
                    file_path=filename,
                    sheet_name=worksheet.title,
                    row_index=row_index,
                    column_index=column_index,
                    column_name=header,
                )
                columns = value_columns(raw)
                population_repo.create_response(
                    session,
                    PopulationResponseRecord(
                        person_id=int(person.id),
                        question_id=int(question.id),
                        source_ref_id=int(source_ref.id),
                        **columns,
                    ),
                )
                if _question_role(header) in {
                    PopulationQuestionRole.demographic,
                    PopulationQuestionRole.metadata,
                    PopulationQuestionRole.quality_control,
                }:
                    population_repo.create_person_attribute(
                        session,
                        PopulationPersonAttributeRecord(
                            person_id=int(person.id),
                            name=slugify(header),
                            **columns,
                        ),
                    )
    return studies, question_count, person_count


def _import_question_catalog(
    session: Session,
    workbook: Any,
    filename: str,
    artifact_id: int,
) -> tuple[list[Any], int]:
    studies = []
    question_count = 0
    for worksheet in workbook.worksheets:
        rows = _sheet_rows(worksheet)
        if len(rows) < 3:
            continue
        external_study_id = _study_id(filename, worksheet.title)
        if population_repo.get_study_by_external_id(session, external_study_id) is not None:
            continue
        study = population_repo.create_study(
            session,
            external_id=external_study_id,
            name=f"Question catalog: {worksheet.title}",
            source_file=filename,
            source_sheet=worksheet.title,
            source_artifact_id=artifact_id,
            description=compact_text(rows[0][0]) if rows[0] and rows[0][0] else None,
            metadata={"catalog_rows": len(rows)},
        )
        studies.append(study)
        for row_index, row in enumerate(rows[2:], start=3):
            wording = compact_text(row[0]) if row and row[0] is not None else ""
            scale_description = compact_text(row[1]) if len(row) > 1 and row[1] is not None else None
            if not wording or (scale_description is None and len(row) <= 2):
                continue
            if scale_description is None and not re.search(r"[?]", wording):
                continue
            source_ref = population_repo.create_source_ref(
                session,
                file_path=filename,
                sheet_name=worksheet.title,
                row_index=row_index,
                column_index=1,
                column_name="Question-item",
            )
            scale = (
                population_repo.create_question_scale(session, raw_description=scale_description)
                if scale_description
                else None
            )
            population_repo.create_question(
                session,
                PopulationQuestionRecord(
                    external_id=f"{slugify(filename, 50)}__{slugify(worksheet.title, 30)}__row{row_index:03d}_{slugify(wording, 45)}",
                    study_id=int(study.id),
                    source_ref_id=int(source_ref.id),
                    scale_id=int(scale.id) if scale else None,
                    kind=_catalog_kind(wording, scale_description),
                    wording=wording,
                    short_name="Question-item",
                    role=_question_role(wording),
                    constructs_json=population_repo.json_dump(_constructs(wording)),
                ),
            )
            question_count += 1
    return studies, question_count


def _study_id(filename: str, sheet_name: str) -> str:
    return f"{slugify(filename)}__{slugify(sheet_name)}"


def _question_id(study_id: str, column_index: int, wording: str) -> str:
    return f"{study_id}__q{column_index:03d}_{slugify(wording, 48)}"


def _scale_for_values(session: Session, values: list[Any]):
    numeric = [value for value in values if isinstance(value, int | float) and not isinstance(value, bool)]
    if not numeric:
        return None
    return population_repo.create_question_scale(session, min_value=float(min(numeric)), max_value=float(max(numeric)))


def _catalog_kind(wording: str, scale_description: str | None) -> PopulationDataKind:
    lower_scale = (scale_description or "").lower()
    if re.search(r"\b0-1\b|\b1-2\b|yes/no|ja/nej", lower_scale):
        return PopulationDataKind.binary
    if re.search(r"\b1-\d+\b", lower_scale):
        return PopulationDataKind.likert if ("agree" in wording.lower() or "enig" in wording.lower()) else PopulationDataKind.ordinal
    if "open" in lower_scale:
        return PopulationDataKind.text
    return _question_kind(wording, [])


def _question_role(wording: str) -> PopulationQuestionRole:
    text = wording.lower()
    if any(term in text for term in ("duration", "status", "completion", "exclude", "attention", "threeminutes")):
        return PopulationQuestionRole.quality_control
    if any(term in text for term in ("age", "alder", "gender", "køn", "region", "postcode", "education", "uddannelse", "household", "hushold", "income", "indkomst")):
        return PopulationQuestionRole.demographic
    if any(term in text for term in ("condition", "gruppe", "group", "route", "produkt", "product", "viser hvilket")):
        return PopulationQuestionRole.experimental_condition
    if "average" in text or "_avg" in text or "score" in text:
        return PopulationQuestionRole.derived
    if any(term in text for term in ("how often", "hvor ofte", "spiser", "eat", "thrown away", "smidt ud", "købt", "buy")):
        return PopulationQuestionRole.behavior
    if any(term in text for term in ("likely", "sandsynligt", "synes du om")):
        return PopulationQuestionRole.preference
    if "agree" in text or "enig" in text or "opfattelse" in text:
        return PopulationQuestionRole.belief
    return PopulationQuestionRole.unknown


def _question_kind(wording: str, values: list[Any]) -> PopulationDataKind:
    role = _question_role(wording)
    text = wording.lower()
    non_missing = [value for value in values if value is not None and compact_text(value) != ""]
    unique = {population_repo.json_dump(jsonable(value)) for value in non_missing}
    if role == PopulationQuestionRole.demographic:
        return PopulationDataKind.demographic
    if role == PopulationQuestionRole.quality_control:
        return PopulationDataKind.attention_or_quality
    if role == PopulationQuestionRole.experimental_condition:
        return PopulationDataKind.experimental_condition
    if role == PopulationQuestionRole.derived:
        return PopulationDataKind.derived
    if any(term in text for term in ("bad/good", "dårligt", "useless/useful", "dumt")):
        return PopulationDataKind.semantic_differential
    if "agree" in text or "enig" in text:
        return PopulationDataKind.likert
    if non_missing and all(isinstance(value, int | float) and not isinstance(value, bool) for value in non_missing):
        if len(unique) <= 2:
            return PopulationDataKind.binary
        if len(unique) <= 12:
            return PopulationDataKind.ordinal
        return PopulationDataKind.numeric
    if len(unique) <= 20:
        return PopulationDataKind.categorical
    return PopulationDataKind.text


def _constructs(wording: str) -> list[str]:
    text = wording.lower()
    rules = {
        "environmental_concern": ("environment", "miljø", "klima", "bæredygtig", "nature", "natur"),
        "meat_reduction": ("kød", "meat", "vegetar", "plant", "plante"),
        "health_orientation": ("health", "sund", "helbred", "protein"),
        "food_waste": ("waste", "thrown away", "smidt ud", "leftover", "bread"),
        "trust": ("trust", "troværdig", "honest", "kompetent"),
        "food_neophilia": ("try new", "nye fødevarer", "usædvanlige"),
        "product_attitude": ("bad/good", "dårligt", "godt", "liking", "synes du om"),
        "purchase_intention": ("buy", "købe", "sandsynligt"),
    }
    return [construct for construct, terms in rules.items() if any(term in text for term in terms)]
