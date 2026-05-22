from __future__ import annotations

import argparse
import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

from sqlmodel import SQLModel, Session, create_engine, select

from models import (
    PopulationArtifactRecord,
    PopulationComparatorKind,
    PopulationComparatorSpecRecord,
    PopulationDataKind,
    PopulationDiagnosticsBalanceVariableRecord,
    PopulationDiagnosticsRecord,
    PopulationFeatureDistanceRecord,
    PopulationMappingInputRecord,
    PopulationMappingStatus,
    PopulationMatchRunRecord,
    PopulationMatchingDefaultRecord,
    PopulationMatchingMethod,
    PopulationMatchingWorkspaceRecord,
    PopulationMissingPolicy,
    PopulationParameterValueKind,
    PopulationPersonAttributeRecord,
    PopulationPersonMatchRecord,
    PopulationPersonRecord,
    PopulationQuestionRecord,
    PopulationQuestionRole,
    PopulationSourceRefRecord,
    PopulationReplacementPolicy,
    PopulationResponseRecord,
    PopulationSpecParameterRecord,
    PopulationTransformInputAliasRecord,
    PopulationTransformKind,
    PopulationTransformSpecRecord,
    PopulationValueKind,
    PopulationVariableSetMappingRecord,
    PopulationWorkspaceAuditEventRecord,
    PopulationWorkspaceNoteRecord,
    PopulationWorkspaceNoteTagRecord,
    PopulationWorkspaceStudyRecord,
    PopulationComparableValueKind,
)
from repositories import population_repo


@dataclass(frozen=True)
class PrototypeMigrationResult:
    artifacts: int = 0
    studies: int = 0
    questions: int = 0
    people: int = 0
    responses: int = 0
    workspaces: int = 0
    mappings: int = 0
    runs: int = 0
    matches: int = 0


def migrate_prototype(session: Session, prototype_root: Path) -> PrototypeMigrationResult:
    result = _MigrationCounts()
    dataset_path = prototype_root / "outputs" / "population_data.json"
    if dataset_path.exists():
        _import_population_dataset(session, prototype_root, dataset_path, result)
    for config_path in sorted((prototype_root / "outputs" / "matching_configs").glob("*.json")):
        _import_matching_config(session, _read_json(config_path), result)
    for run_path in sorted((prototype_root / "outputs" / "matching_runs").glob("*.json")):
        _import_matching_run(session, _read_json(run_path), result)
    session.commit()
    return PrototypeMigrationResult(**result.__dict__)


@dataclass
class _MigrationCounts:
    artifacts: int = 0
    studies: int = 0
    questions: int = 0
    people: int = 0
    responses: int = 0
    workspaces: int = 0
    mappings: int = 0
    runs: int = 0
    matches: int = 0


def _import_population_dataset(
    session: Session,
    prototype_root: Path,
    dataset_path: Path,
    result: _MigrationCounts,
) -> None:
    payload = _read_json(dataset_path)
    artifacts_by_source = {
        source_file: _artifact_for_source(session, prototype_root, source_file, result)
        for source_file in {study["source_file"] for study in payload.get("studies", [])}
    }
    studies_by_source = _import_studies(session, payload.get("studies", []), artifacts_by_source, result)
    questions_by_source = _import_questions(session, payload.get("questions", []), studies_by_source, result)
    _import_people(session, payload.get("people", []), studies_by_source, questions_by_source, result)


def _artifact_for_source(
    session: Session,
    prototype_root: Path,
    source_file: str,
    result: _MigrationCounts,
) -> PopulationArtifactRecord | None:
    source_path = prototype_root / source_file
    if not source_path.is_file():
        return None
    content = source_path.read_bytes()
    fingerprint = hashlib.sha256(content).hexdigest()
    artifact = population_repo.get_artifact_by_fingerprint(session, fingerprint)
    if artifact is not None:
        return artifact
    result.artifacts += 1
    return population_repo.create_artifact(
        session,
        filename=source_file,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        fingerprint=fingerprint,
        content=content,
        metadata={"import_kind": "prototype_source", "prototype_source_file": source_file},
    )


def _import_studies(
    session: Session,
    studies: Iterable[dict[str, Any]],
    artifacts_by_source: dict[str, PopulationArtifactRecord | None],
    result: _MigrationCounts,
) -> dict[tuple[str, str], Any]:
    imported = {}
    for study in studies:
        external_id = _study_external_id(session, study["id"], study["source_file"])
        row = population_repo.get_study_by_external_id(session, external_id)
        if row is None:
            artifact = artifacts_by_source.get(study["source_file"])
            row = population_repo.create_study(
                session,
                external_id=external_id,
                name=study["name"],
                source_file=study["source_file"],
                source_sheet=study.get("source_sheet"),
                source_artifact_id=int(artifact.id) if artifact and artifact.id is not None else None,
                description=study.get("description"),
                collected_at=study.get("collected_at"),
                metadata=study.get("metadata", {}),
            )
            result.studies += 1
        imported[(study["id"], study["source_file"])] = row
    return imported


def _import_questions(
    session: Session,
    questions: Iterable[dict[str, Any]],
    studies_by_source: dict[tuple[str, str], Any],
    result: _MigrationCounts,
) -> dict[tuple[str, str, str | None, int | None], PopulationQuestionRecord]:
    imported = {}
    for question in questions:
        source = question["source"]
        study = studies_by_source.get((question["study_id"], source["file_path"]))
        external_id = _child_external_id(question["id"], study, question["study_id"]) if study else question["id"]
        external_id = _question_external_id(session, external_id, source)
        row = population_repo.get_question_by_external_id(session, external_id)
        if row is None and study is not None:
            source_ref = population_repo.create_source_ref(session, **source)
            scale = _import_scale(session, question.get("scale"))
            row = population_repo.create_question(
                session,
                PopulationQuestionRecord(
                    external_id=external_id,
                    study_id=int(study.id),
                    source_ref_id=int(source_ref.id),
                    scale_id=int(scale.id) if scale and scale.id is not None else None,
                    kind=_enum(PopulationDataKind, question.get("kind"), PopulationDataKind.unknown),
                    wording=question["wording"],
                    short_name=question.get("short_name"),
                    role=_enum(PopulationQuestionRole, question.get("role"), PopulationQuestionRole.unknown),
                    constructs_json=population_repo.json_dump(question.get("constructs", [])),
                    missing_codes_json=population_repo.json_dump(question.get("missing_codes", [])),
                    reverse_scored=bool(question.get("reverse_scored", False)),
                    harmonized_variable_id=question.get("harmonized_variable_id"),
                    metadata_json=population_repo.json_dump(question.get("metadata", {})),
                ),
            )
            result.questions += 1
        if row is not None:
            imported[_question_source_key(question["id"], source)] = row
    return imported


def _import_scale(session: Session, scale: dict[str, Any] | None):
    if not scale:
        return None
    return population_repo.create_question_scale(
        session,
        min_value=scale.get("min_value"),
        max_value=scale.get("max_value"),
        min_label=scale.get("min_label"),
        max_label=scale.get("max_label"),
        step=scale.get("step"),
        raw_description=scale.get("raw_description"),
        options=scale.get("options", []),
    )


def _import_people(
    session: Session,
    people: Iterable[dict[str, Any]],
    studies_by_source: dict[tuple[str, str], Any],
    questions_by_source: dict[tuple[str, str, str | None, int | None], PopulationQuestionRecord],
    result: _MigrationCounts,
) -> None:
    for person in people:
        person_source = person["source"]
        study = studies_by_source.get((person["study_id"], person_source["file_path"]))
        external_id = _child_external_id(person["id"], study, person["study_id"]) if study else person["id"]
        row = population_repo.get_person_by_external_id(session, external_id)
        if row is not None or study is None:
            continue
        source_ref = population_repo.create_source_ref(session, **person_source)
        row = population_repo.create_person(
            session,
            PopulationPersonRecord(
                external_id=external_id,
                study_id=int(study.id),
                source_ref_id=int(source_ref.id),
                source_person_id=_optional_string(person.get("source_person_id")),
                metadata_json=population_repo.json_dump(person.get("metadata", {})),
            ),
        )
        result.people += 1
        for name, value in person.get("attributes", {}).items():
            population_repo.create_person_attribute(
                session,
                PopulationPersonAttributeRecord(person_id=int(row.id), name=name, **_value_columns(value)),
            )
        for name, value in person.get("weights", {}).items():
            population_repo.create_person_weight(session, person_id=int(row.id), name=name, value=float(value))
        for response in person.get("responses", []):
            response_source = response["source"]
            question = questions_by_source.get(_question_source_key(response["question_id"], response_source))
            if question is None:
                continue
            source_ref = population_repo.create_source_ref(session, **response_source)
            population_repo.create_response(
                session,
                PopulationResponseRecord(
                    person_id=int(row.id),
                    question_id=int(question.id),
                    source_ref_id=int(source_ref.id),
                    metadata_json=population_repo.json_dump(response.get("metadata", {})),
                    **_value_columns(response.get("value", {})),
                ),
            )
            result.responses += 1


def _import_matching_config(session: Session, config: dict[str, Any], result: _MigrationCounts) -> None:
    if _workspace_by_external_id(session, config["config_id"]) is not None:
        return
    source_study = _study(session, config.get("primary_source_study_id"))
    target_study = _study(session, config.get("primary_target_study_id"))
    workspace = PopulationMatchingWorkspaceRecord(
        external_id=config["config_id"],
        schema_version=config.get("schema_version", "0.2.0"),
        name=config.get("name") or config["config_id"],
        description=config.get("description"),
        dataset_fingerprint=config.get("dataset_fingerprint"),
        primary_source_study_id=int(source_study.id) if source_study else None,
        primary_target_study_id=int(target_study.id) if target_study else None,
        created_at=_datetime(config.get("created_at")),
        updated_at=_datetime(config.get("updated_at")),
    )
    session.add(workspace)
    session.flush()
    result.workspaces += 1
    for order, study_external_id in enumerate(config.get("study_ids", [])):
        study = _study(session, study_external_id)
        if study is not None:
            session.add(PopulationWorkspaceStudyRecord(workspace_id=int(workspace.id), study_id=int(study.id), order_index=order))
    _import_matching_defaults(session, workspace, config.get("matching_defaults", {}))
    _import_diagnostics(session, workspace, config.get("diagnostics", {}))
    for mapping in config.get("variable_set_mappings", []):
        if _import_mapping(session, workspace, mapping):
            result.mappings += 1
    _import_notes(session, workspace, config.get("notes", []))
    _import_audit_events(session, workspace, config.get("audit_events", []))


def _import_matching_defaults(session: Session, workspace: Any, defaults: dict[str, Any]) -> None:
    source_study = _study(session, defaults.get("source_study_id"))
    target_study = _study(session, defaults.get("target_study_id"))
    session.add(
        PopulationMatchingDefaultRecord(
            workspace_id=int(workspace.id),
            method=_enum(PopulationMatchingMethod, defaults.get("method"), PopulationMatchingMethod.weighted_knn),
            k=int(defaults.get("k", 5)),
            source_study_id=int(source_study.id) if source_study else None,
            target_study_id=int(target_study.id) if target_study else None,
            replacement_policy=_enum(
                PopulationReplacementPolicy,
                defaults.get("replacement_policy"),
                PopulationReplacementPolicy.allow_reuse,
            ),
            capped_reuse_limit=defaults.get("capped_reuse_limit"),
            caliper=defaults.get("caliper"),
            missing_policy=_enum(PopulationMissingPolicy, defaults.get("missing_policy"), PopulationMissingPolicy.pairwise_ignore),
            normalize_weights=bool(defaults.get("normalize_weights", True)),
            random_seed=int(defaults.get("random_seed", 42)),
            notes=defaults.get("notes"),
        )
    )


def _import_diagnostics(session: Session, workspace: Any, diagnostics: dict[str, Any]) -> None:
    row = PopulationDiagnosticsRecord(
        workspace_id=int(workspace.id),
        compare_distributions=bool(diagnostics.get("compare_distributions", True)),
        show_worst_matches=bool(diagnostics.get("show_worst_matches", True)),
        show_feature_contributions=bool(diagnostics.get("show_feature_contributions", True)),
    )
    session.add(row)
    session.flush()
    for balance_variable in diagnostics.get("balance_variables", []):
        session.add(PopulationDiagnosticsBalanceVariableRecord(diagnostics_id=int(row.id), variable_name=balance_variable))


def _import_mapping(session: Session, workspace: Any, mapping: dict[str, Any]) -> bool:
    left_study = _study(session, mapping.get("left_study_id"))
    right_study = _study(session, mapping.get("right_study_id"))
    if left_study is None or right_study is None:
        return False
    row = PopulationVariableSetMappingRecord(
        external_id=mapping["mapping_id"],
        workspace_id=int(workspace.id),
        name=mapping.get("name") or mapping["mapping_id"],
        description=mapping.get("description"),
        left_study_id=int(left_study.id),
        right_study_id=int(right_study.id),
        output_kind=_enum(PopulationComparableValueKind, mapping.get("output_kind"), PopulationComparableValueKind.number),
        weight=float(mapping.get("weight", 1.0)),
        status=_enum(PopulationMappingStatus, mapping.get("status"), PopulationMappingStatus.approved),
        notes=mapping.get("notes"),
        created_at=_datetime(mapping.get("created_at")),
        updated_at=_datetime(mapping.get("updated_at")),
    )
    session.add(row)
    session.flush()
    _import_mapping_inputs(session, row, "left", mapping.get("left_inputs", []))
    _import_mapping_inputs(session, row, "right", mapping.get("right_inputs", []))
    _import_transform(session, row, "left", mapping.get("left_transform", {}))
    _import_transform(session, row, "right", mapping.get("right_transform", {}))
    _import_comparator(session, row, mapping.get("comparator", {}))
    return True


def _import_mapping_inputs(session: Session, mapping: Any, side: str, inputs: Iterable[dict[str, Any]]) -> None:
    for order, input_spec in enumerate(inputs):
        question = _question(session, input_spec.get("question_id"))
        if question is not None:
            session.add(
                PopulationMappingInputRecord(
                    mapping_id=int(mapping.id),
                    question_id=int(question.id),
                    side=side,
                    alias=input_spec.get("alias") or f"{side}_{order}",
                    required=bool(input_spec.get("required", True)),
                    order_index=order,
                )
            )


def _import_transform(session: Session, mapping: Any, side: str, transform: dict[str, Any]) -> None:
    row = PopulationTransformSpecRecord(
        mapping_id=int(mapping.id),
        side=side,
        kind=_enum(PopulationTransformKind, transform.get("kind"), PopulationTransformKind.identity),
        output_alias=transform.get("output_alias", "value"),
        notes=transform.get("notes"),
    )
    session.add(row)
    session.flush()
    for order, alias in enumerate(transform.get("input_aliases", [])):
        session.add(PopulationTransformInputAliasRecord(transform_id=int(row.id), alias=alias, order_index=order))
    _import_parameters(session, transform_id=int(row.id), value=transform.get("parameters", {}))


def _import_comparator(session: Session, mapping: Any, comparator: dict[str, Any]) -> None:
    row = PopulationComparatorSpecRecord(
        mapping_id=int(mapping.id),
        kind=_enum(PopulationComparatorKind, comparator.get("kind"), PopulationComparatorKind.exact_match),
        missing_policy=_enum(PopulationMissingPolicy, comparator.get("missing_policy"), PopulationMissingPolicy.pairwise_ignore),
        notes=comparator.get("notes"),
    )
    session.add(row)
    session.flush()
    _import_parameters(session, comparator_id=int(row.id), value=comparator.get("parameters", {}))


def _import_parameters(
    session: Session,
    *,
    value: Any,
    transform_id: int | None = None,
    comparator_id: int | None = None,
    parent_id: int | None = None,
    key: str | None = None,
    order_index: int = 0,
) -> None:
    if parent_id is None and key is None and isinstance(value, dict):
        for order, (child_key, child_value) in enumerate(value.items()):
            _import_parameters(
                session,
                transform_id=transform_id,
                comparator_id=comparator_id,
                value=child_value,
                key=child_key,
                order_index=order,
            )
        return
    row = PopulationSpecParameterRecord(
        transform_id=transform_id if parent_id is None else None,
        comparator_id=comparator_id if parent_id is None else None,
        parent_id=parent_id,
        key=key,
        order_index=order_index,
        **_parameter_columns(value),
    )
    session.add(row)
    session.flush()
    if isinstance(value, dict):
        children = value.items()
    elif isinstance(value, list):
        children = ((None, item) for item in value)
    else:
        return
    for order, (child_key, child_value) in enumerate(children):
        _import_parameters(session, value=child_value, parent_id=int(row.id), key=child_key, order_index=order)


def _parameter_columns(value: Any) -> dict[str, Any]:
    if isinstance(value, bool):
        return {"value_kind": PopulationParameterValueKind.boolean, "value_bool": value}
    if isinstance(value, int):
        return {"value_kind": PopulationParameterValueKind.integer, "value_integer": value}
    if isinstance(value, float):
        return {"value_kind": PopulationParameterValueKind.number, "value_number": value}
    if isinstance(value, str):
        return {"value_kind": PopulationParameterValueKind.string, "value_string": value}
    return {"value_kind": PopulationParameterValueKind.null}


def _import_notes(session: Session, workspace: Any, notes: Iterable[dict[str, Any]]) -> None:
    for note in notes:
        row = PopulationWorkspaceNoteRecord(
            external_id=note["note_id"],
            workspace_id=int(workspace.id),
            text=note["text"],
            scope=note.get("scope", "workspace"),
            object_external_id=note.get("object_id"),
            created_at=_datetime(note.get("created_at")),
            updated_at=_datetime(note.get("updated_at")),
        )
        session.add(row)
        session.flush()
        for tag in note.get("tags", []):
            session.add(PopulationWorkspaceNoteTagRecord(note_id=int(row.id), tag=tag))


def _import_audit_events(session: Session, workspace: Any, audit_events: Iterable[dict[str, Any]]) -> None:
    for event in audit_events:
        session.add(
            PopulationWorkspaceAuditEventRecord(
                workspace_id=int(workspace.id),
                timestamp=_datetime(event.get("timestamp")),
                event_type=event["event_type"],
                message=event["message"],
                object_external_id=event.get("object_id"),
                metadata_json=population_repo.json_dump(event.get("metadata", {})),
            )
        )


def _import_matching_run(session: Session, run: dict[str, Any], result: _MigrationCounts) -> None:
    if _run_by_external_id(session, run["run_id"]) is not None:
        return
    workspace = _workspace_by_external_id(session, run.get("config_id"))
    source_study = _study(session, run.get("source_study_id"))
    target_study = _study(session, run.get("target_study_id"))
    if workspace is None or source_study is None or target_study is None:
        return
    summary = run.get("summary", {})
    row = PopulationMatchRunRecord(
        external_id=run["run_id"],
        workspace_id=int(workspace.id),
        source_study_id=int(source_study.id),
        target_study_id=int(target_study.id),
        created_at=_datetime(run.get("created_at")),
        method=_enum(PopulationMatchingMethod, run.get("method"), PopulationMatchingMethod.weighted_knn),
        k=int(run.get("k", 5)),
        source_people_evaluated=int(summary.get("source_people_evaluated", 0)),
        target_people_available=int(summary.get("target_people_available", 0)),
        approved_mappings_used=int(summary.get("approved_mappings_used", 0)),
        match_count=int(summary.get("match_count", len(run.get("matches", [])))),
        average_distance=summary.get("average_distance"),
        summary_json=population_repo.json_dump(summary),
    )
    session.add(row)
    session.flush()
    result.runs += 1
    rank_by_source: dict[str, int] = {}
    for match in run.get("matches", []):
        source = _person(session, match.get("source_person_id"))
        target = _person(session, match.get("target_person_id"))
        if source is None or target is None:
            continue
        source_external_id = match["source_person_id"]
        rank_by_source[source_external_id] = rank_by_source.get(source_external_id, 0) + 1
        match_row = PopulationPersonMatchRecord(
            run_id=int(row.id),
            source_person_id=int(source.id),
            target_person_id=int(target.id),
            distance=float(match["distance"]),
            similarity=float(match["similarity"]),
            matched_features_count=int(match.get("matched_features_count", 0)),
            missing_features_count=int(match.get("missing_features_count", 0)),
            rank=rank_by_source[source_external_id],
        )
        session.add(match_row)
        session.flush()
        result.matches += 1
        _import_feature_distances(session, match_row, match.get("feature_distances", []))


def _import_feature_distances(session: Session, match: Any, features: Iterable[dict[str, Any]]) -> None:
    for feature in features:
        mapping = _mapping(session, feature.get("mapping_id"))
        session.add(
            PopulationFeatureDistanceRecord(
                person_match_id=int(match.id),
                mapping_id=int(mapping.id) if mapping else None,
                mapping_external_id=feature["mapping_id"],
                mapping_name=feature.get("mapping_name") or feature["mapping_id"],
                distance=feature.get("distance"),
                weight=float(feature.get("weight", 0.0)),
                source_value_json=population_repo.json_dump(feature.get("source_value")),
                target_value_json=population_repo.json_dump(feature.get("target_value")),
                missing=bool(feature.get("missing", False)),
            )
        )


def _value_columns(value: dict[str, Any]) -> dict[str, Any]:
    return {
        "value_kind": _enum(PopulationValueKind, value.get("kind"), PopulationValueKind.missing),
        "raw_json": population_repo.json_dump(value.get("raw")),
        "normalized_json": population_repo.json_dump(value.get("normalized")),
        "label": value.get("label"),
        "is_missing": bool(value.get("is_missing", False)),
    }


def _study(session: Session, external_id: str | None):
    return population_repo.get_study_by_external_id(session, external_id) if external_id else None


def _study_external_id(session: Session, external_id: str, source_file: str) -> str:
    row = population_repo.get_study_by_external_id(session, external_id)
    if row is None or row.source_file == source_file:
        return external_id
    return f"{external_id}__source_{_external_hash(source_file)}"


def _question_external_id(session: Session, external_id: str, source: dict[str, Any]) -> str:
    row = population_repo.get_question_by_external_id(session, external_id)
    if row is None or _question_row_matches_source(session, row, source):
        return external_id
    source_identity = population_repo.json_dump(
        {
            "file_path": source.get("file_path"),
            "sheet_name": source.get("sheet_name"),
            "row_index": source.get("row_index"),
            "column_index": source.get("column_index"),
        }
    )
    return f"{external_id}__source_ref_{_external_hash(source_identity)}"


def _question_row_matches_source(session: Session, question: PopulationQuestionRecord, source: dict[str, Any]) -> bool:
    source_ref = session.get(PopulationSourceRefRecord, question.source_ref_id)
    return bool(
        source_ref
        and source_ref.file_path == source.get("file_path")
        and source_ref.sheet_name == source.get("sheet_name")
        and source_ref.row_index == source.get("row_index")
        and source_ref.column_index == source.get("column_index")
    )


def _question_source_key(external_id: str, source: dict[str, Any]) -> tuple[str, str, str | None, int | None]:
    return (external_id, source["file_path"], source.get("sheet_name"), source.get("column_index"))


def _child_external_id(external_id: str, study: Any, original_study_id: str) -> str:
    if study.external_id == original_study_id:
        return external_id
    return f"{external_id}__study_{_external_hash(study.external_id)}"


def _external_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:10]


def _question(session: Session, external_id: str | None):
    return population_repo.get_question_by_external_id(session, external_id) if external_id else None


def _person(session: Session, external_id: str | None):
    return population_repo.get_person_by_external_id(session, external_id) if external_id else None


def _workspace_by_external_id(session: Session, external_id: str | None):
    if not external_id:
        return None
    return session.exec(
        select(PopulationMatchingWorkspaceRecord).where(PopulationMatchingWorkspaceRecord.external_id == external_id)
    ).first()


def _mapping(session: Session, external_id: str | None):
    if not external_id:
        return None
    return session.exec(
        select(PopulationVariableSetMappingRecord).where(PopulationVariableSetMappingRecord.external_id == external_id)
    ).first()


def _run_by_external_id(session: Session, external_id: str):
    return session.exec(select(PopulationMatchRunRecord).where(PopulationMatchRunRecord.external_id == external_id)).first()


def _enum(enum_type, value: Any, default):
    try:
        return enum_type(value)
    except (TypeError, ValueError):
        return default


def _datetime(value: str | None) -> datetime:
    return datetime.fromisoformat(value) if value else datetime.utcnow()


def _optional_string(value: Any) -> str | None:
    return None if value is None else str(value)


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> None:
    parser = argparse.ArgumentParser(description="Import prototype population_data outputs into a SQLModel database.")
    parser.add_argument("prototype_root", type=Path, nargs="?", default=Path("population_data"))
    parser.add_argument("--db-url", default="sqlite:///behavior_manager.db")
    args = parser.parse_args()
    engine = create_engine(args.db_url)
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        result = migrate_prototype(session, args.prototype_root)
    print(result)


if __name__ == "__main__":
    main()
