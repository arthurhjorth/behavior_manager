from __future__ import annotations

import json
from collections.abc import Iterable
from typing import Any

from sqlmodel import Session, col, func, select

from models import (
    PopulationArtifactRecord,
    PopulationPersonAttributeRecord,
    PopulationPersonRecord,
    PopulationPersonWeightRecord,
    PopulationQuestionOptionRecord,
    PopulationQuestionRecord,
    PopulationQuestionScaleRecord,
    PopulationResponseRecord,
    PopulationSourceRefRecord,
    PopulationStudyRecord,
)


def json_dump(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def json_load(value: str | None, default: Any) -> Any:
    if not value:
        return default
    return json.loads(value)


def create_artifact(
    session: Session,
    *,
    filename: str,
    media_type: str,
    fingerprint: str,
    content: bytes,
    metadata: dict[str, Any] | None = None,
) -> PopulationArtifactRecord:
    row = PopulationArtifactRecord(
        filename=filename,
        media_type=media_type,
        fingerprint=fingerprint,
        byte_size=len(content),
        content=content,
        metadata_json=json_dump(metadata or {}),
    )
    session.add(row)
    session.flush()
    return row


def get_artifact_by_fingerprint(session: Session, fingerprint: str) -> PopulationArtifactRecord | None:
    return session.exec(
        select(PopulationArtifactRecord).where(PopulationArtifactRecord.fingerprint == fingerprint)
    ).first()


def create_source_ref(
    session: Session,
    *,
    file_path: str,
    sheet_name: str | None = None,
    row_index: int | None = None,
    column_index: int | None = None,
    column_name: str | None = None,
) -> PopulationSourceRefRecord:
    row = PopulationSourceRefRecord(
        file_path=file_path,
        sheet_name=sheet_name,
        row_index=row_index,
        column_index=column_index,
        column_name=column_name,
    )
    session.add(row)
    session.flush()
    return row


def get_study_by_external_id(session: Session, external_id: str) -> PopulationStudyRecord | None:
    return session.exec(
        select(PopulationStudyRecord).where(PopulationStudyRecord.external_id == external_id)
    ).first()


def list_studies(session: Session) -> list[PopulationStudyRecord]:
    return list(session.exec(select(PopulationStudyRecord).order_by(PopulationStudyRecord.name, PopulationStudyRecord.id)))


def create_study(
    session: Session,
    *,
    external_id: str,
    name: str,
    source_file: str,
    source_sheet: str | None = None,
    source_artifact_id: int | None = None,
    description: str | None = None,
    collected_at: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> PopulationStudyRecord:
    row = PopulationStudyRecord(
        external_id=external_id,
        name=name,
        source_file=source_file,
        source_sheet=source_sheet,
        source_artifact_id=source_artifact_id,
        description=description,
        collected_at=collected_at,
        metadata_json=json_dump(metadata or {}),
    )
    session.add(row)
    session.flush()
    return row


def get_question_by_external_id(session: Session, external_id: str) -> PopulationQuestionRecord | None:
    return session.exec(
        select(PopulationQuestionRecord).where(PopulationQuestionRecord.external_id == external_id)
    ).first()


def list_questions(
    session: Session,
    *,
    study_id: int | None = None,
    search: str | None = None,
    limit: int | None = None,
) -> list[PopulationQuestionRecord]:
    statement = select(PopulationQuestionRecord)
    if study_id is not None:
        statement = statement.where(PopulationQuestionRecord.study_id == study_id)
    if search:
        statement = statement.where(col(PopulationQuestionRecord.wording).contains(search))
    statement = statement.order_by(PopulationQuestionRecord.study_id, PopulationQuestionRecord.id)
    if limit is not None:
        statement = statement.limit(limit)
    return list(session.exec(statement))


def create_question_scale(
    session: Session,
    *,
    min_value: float | None = None,
    max_value: float | None = None,
    min_label: str | None = None,
    max_label: str | None = None,
    step: float | None = None,
    raw_description: str | None = None,
    options: Iterable[dict[str, Any]] = (),
) -> PopulationQuestionScaleRecord:
    scale = PopulationQuestionScaleRecord(
        min_value=min_value,
        max_value=max_value,
        min_label=min_label,
        max_label=max_label,
        step=step,
        raw_description=raw_description,
    )
    session.add(scale)
    session.flush()
    for option in options:
        session.add(
            PopulationQuestionOptionRecord(
                scale_id=int(scale.id),
                value_json=json_dump(option.get("value")),
                label=option.get("label"),
                order_index=option.get("order"),
                is_missing=bool(option.get("is_missing", False)),
            )
        )
    return scale


def create_question(session: Session, question: PopulationQuestionRecord) -> PopulationQuestionRecord:
    session.add(question)
    session.flush()
    return question


def get_person_by_external_id(session: Session, external_id: str) -> PopulationPersonRecord | None:
    return session.exec(
        select(PopulationPersonRecord).where(PopulationPersonRecord.external_id == external_id)
    ).first()


def list_people(
    session: Session,
    *,
    study_id: int,
    offset: int = 0,
    limit: int = 50,
) -> list[PopulationPersonRecord]:
    return list(
        session.exec(
            select(PopulationPersonRecord)
            .where(PopulationPersonRecord.study_id == study_id)
            .order_by(PopulationPersonRecord.id)
            .offset(offset)
            .limit(limit)
        )
    )


def count_people(session: Session, study_id: int) -> int:
    return int(
        session.exec(
            select(func.count()).select_from(PopulationPersonRecord).where(PopulationPersonRecord.study_id == study_id)
        ).one()
    )


def count_questions(session: Session, study_id: int) -> int:
    return int(
        session.exec(
            select(func.count()).select_from(PopulationQuestionRecord).where(PopulationQuestionRecord.study_id == study_id)
        ).one()
    )


def create_person(session: Session, person: PopulationPersonRecord) -> PopulationPersonRecord:
    session.add(person)
    session.flush()
    return person


def create_person_attribute(session: Session, attribute: PopulationPersonAttributeRecord) -> PopulationPersonAttributeRecord:
    session.add(attribute)
    session.flush()
    return attribute


def create_person_weight(
    session: Session,
    *,
    person_id: int,
    name: str,
    value: float,
) -> PopulationPersonWeightRecord:
    row = PopulationPersonWeightRecord(person_id=person_id, name=name, value=value)
    session.add(row)
    session.flush()
    return row


def create_response(session: Session, response: PopulationResponseRecord) -> PopulationResponseRecord:
    session.add(response)
    session.flush()
    return response


def list_responses(session: Session, person_id: int) -> list[PopulationResponseRecord]:
    return list(
        session.exec(
            select(PopulationResponseRecord)
            .where(PopulationResponseRecord.person_id == person_id)
            .order_by(PopulationResponseRecord.question_id)
        )
    )
