from __future__ import annotations

from datetime import datetime
from typing import Any, Iterable

from sqlmodel import Session, select

from models import (
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
from population_data.models import (
    AttentionOrQualityQuestion,
    BinaryQuestion,
    CategoricalQuestion,
    DataKind,
    DemographicQuestion,
    DerivedQuestion,
    ExperimentalConditionQuestion,
    LikertQuestion,
    MultiSelectQuestion,
    NumericQuestion,
    Option,
    OrdinalQuestion,
    Person,
    PopulationDataset,
    Question,
    QuestionRole,
    Response,
    ResponseValue,
    Scale,
    SemanticDifferentialQuestion,
    SourceRef,
    Study,
    TextQuestion,
    ValueKind,
)
from repositories import population_repo


def export_population_dataset(
    session: Session,
    *,
    study_ids: Iterable[int] | None = None,
    include_people: bool = True,
) -> PopulationDataset:
    selected_studies = _selected_studies(session, study_ids)
    selected_study_ids = [int(study.id) for study in selected_studies if study.id is not None]
    questions = _questions_for_studies(session, selected_study_ids)

    return PopulationDataset(
        studies=[_study_model(study) for study in selected_studies],
        questions=[_question_model(session, question) for question in questions],
        people=_people_models(session, selected_study_ids, questions) if include_people else [],
        metadata={
            "exported_at": datetime.utcnow().isoformat(),
            "study_count": len(selected_studies),
            "question_count": len(questions),
            "include_people": include_people,
            "format": "population_data.models.PopulationDataset",
        },
    )


def _selected_studies(session: Session, study_ids: Iterable[int] | None) -> list[PopulationStudyRecord]:
    if study_ids is None:
        return population_repo.list_studies(session)
    ids = [int(study_id) for study_id in study_ids]
    if not ids:
        return []
    return list(
        session.exec(
            select(PopulationStudyRecord)
            .where(PopulationStudyRecord.id.in_(ids))
            .order_by(PopulationStudyRecord.name, PopulationStudyRecord.id)
        )
    )


def _questions_for_studies(session: Session, study_ids: list[int]) -> list[PopulationQuestionRecord]:
    if not study_ids:
        return []
    return list(
        session.exec(
            select(PopulationQuestionRecord)
            .where(PopulationQuestionRecord.study_id.in_(study_ids))
            .order_by(PopulationQuestionRecord.study_id, PopulationQuestionRecord.id)
        )
    )


def _study_model(study: PopulationStudyRecord) -> Study:
    return Study(
        id=study.external_id,
        name=study.name,
        source_file=study.source_file,
        source_sheet=study.source_sheet,
        description=study.description,
        collected_at=study.collected_at,
        metadata=population_repo.json_load(study.metadata_json, {}),
    )


def _question_model(session: Session, question: PopulationQuestionRecord) -> Question:
    base = {
        "id": question.external_id,
        "study_id": _study_external_id(session, question.study_id),
        "wording": question.wording,
        "source": _source_model(session, question.source_ref_id),
        "short_name": question.short_name,
        "role": _role(question.role.value),
        "constructs": population_repo.json_load(question.constructs_json, []),
        "scale": _scale_model(session, question.scale_id),
        "missing_codes": population_repo.json_load(question.missing_codes_json, []),
        "reverse_scored": question.reverse_scored,
        "harmonized_variable_id": question.harmonized_variable_id,
        "metadata": population_repo.json_load(question.metadata_json, {}),
    }
    kind = _kind(question.kind.value)
    if kind == DataKind.NUMERIC:
        return NumericQuestion(**base)
    if kind == DataKind.ORDINAL:
        return OrdinalQuestion(**base)
    if kind == DataKind.LIKERT:
        return LikertQuestion(**base)
    if kind == DataKind.SEMANTIC_DIFFERENTIAL:
        return SemanticDifferentialQuestion(**base)
    if kind == DataKind.BINARY:
        return BinaryQuestion(**base)
    if kind == DataKind.EXPERIMENTAL_CONDITION:
        return ExperimentalConditionQuestion(**base)
    if kind == DataKind.MULTI_SELECT:
        return MultiSelectQuestion(**base)
    if kind == DataKind.TEXT:
        return TextQuestion(**base)
    if kind == DataKind.DERIVED:
        return DerivedQuestion(**base)
    if kind == DataKind.ATTENTION_OR_QUALITY:
        return AttentionOrQualityQuestion(**base)
    if kind == DataKind.DEMOGRAPHIC:
        return DemographicQuestion(**base)
    return CategoricalQuestion(**base)


def _scale_model(session: Session, scale_id: int | None) -> Scale | None:
    if scale_id is None:
        return None
    scale = session.get(PopulationQuestionScaleRecord, scale_id)
    if scale is None:
        return None
    options = list(
        session.exec(
            select(PopulationQuestionOptionRecord)
            .where(PopulationQuestionOptionRecord.scale_id == scale_id)
            .order_by(PopulationQuestionOptionRecord.order_index, PopulationQuestionOptionRecord.id)
        )
    )
    return Scale(
        min_value=scale.min_value,
        max_value=scale.max_value,
        min_label=scale.min_label,
        max_label=scale.max_label,
        step=scale.step,
        raw_description=scale.raw_description,
        options=[
            Option(
                value=population_repo.json_load(option.value_json, None),
                label=option.label,
                order=option.order_index,
                is_missing=option.is_missing,
            )
            for option in options
        ],
    )


def _people_models(
    session: Session,
    study_ids: list[int],
    questions: list[PopulationQuestionRecord],
) -> list[Person]:
    if not study_ids:
        return []
    question_external_ids = {int(question.id): question.external_id for question in questions if question.id is not None}
    people = list(
        session.exec(
            select(PopulationPersonRecord)
            .where(PopulationPersonRecord.study_id.in_(study_ids))
            .order_by(PopulationPersonRecord.study_id, PopulationPersonRecord.id)
        )
    )
    return [_person_model(session, person, question_external_ids) for person in people]


def _person_model(session: Session, person: PopulationPersonRecord, question_external_ids: dict[int, str]) -> Person:
    responses = list(
        session.exec(
            select(PopulationResponseRecord)
            .where(PopulationResponseRecord.person_id == person.id)
            .order_by(PopulationResponseRecord.question_id)
        )
    )
    attributes = list(
        session.exec(
            select(PopulationPersonAttributeRecord)
            .where(PopulationPersonAttributeRecord.person_id == person.id)
            .order_by(PopulationPersonAttributeRecord.name)
        )
    )
    weights = list(
        session.exec(
            select(PopulationPersonWeightRecord)
            .where(PopulationPersonWeightRecord.person_id == person.id)
            .order_by(PopulationPersonWeightRecord.name)
        )
    )
    return Person(
        id=person.external_id,
        study_id=_study_external_id(session, person.study_id),
        source_person_id=person.source_person_id,
        source=_source_model(session, person.source_ref_id),
        metadata=population_repo.json_load(person.metadata_json, {}),
        attributes={attribute.name: _value_model(attribute) for attribute in attributes},
        weights={weight.name: weight.value for weight in weights},
        responses=[
            Response(
                question_id=question_external_ids[response.question_id],
                value=_value_model(response),
                source=_source_model(session, response.source_ref_id),
                metadata=population_repo.json_load(response.metadata_json, {}),
            )
            for response in responses
            if response.question_id in question_external_ids
        ],
    )


def _value_model(row: Any) -> ResponseValue:
    return ResponseValue(
        kind=_value_kind(row.value_kind.value),
        raw=population_repo.json_load(row.raw_json, None),
        normalized=population_repo.json_load(row.normalized_json, None),
        label=row.label,
        is_missing=row.is_missing,
    )


def _source_model(session: Session, source_ref_id: int) -> SourceRef:
    source = session.get(PopulationSourceRefRecord, source_ref_id)
    if source is None:
        return SourceRef(file_path="unknown")
    return SourceRef(
        file_path=source.file_path,
        sheet_name=source.sheet_name,
        row_index=source.row_index,
        column_index=source.column_index,
        column_name=source.column_name,
    )


def _study_external_id(session: Session, study_id: int) -> str:
    study = session.get(PopulationStudyRecord, study_id)
    if study is None:
        raise ValueError(f"Study not found: {study_id}")
    return study.external_id


def _kind(value: str) -> DataKind:
    try:
        return DataKind(value)
    except ValueError:
        return DataKind.UNKNOWN


def _role(value: str) -> QuestionRole:
    try:
        return QuestionRole(value)
    except ValueError:
        return QuestionRole.UNKNOWN


def _value_kind(value: str) -> ValueKind:
    try:
        return ValueKind(value)
    except ValueError:
        return ValueKind.MISSING
