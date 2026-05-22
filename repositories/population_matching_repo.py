from __future__ import annotations

from datetime import datetime
from typing import Any, Iterable
from uuid import uuid4

from sqlmodel import Session, select

from models import (
    PopulationComparatorKind,
    PopulationComparatorSpecRecord,
    PopulationDiagnosticsRecord,
    PopulationMappingInputRecord,
    PopulationMappingStatus,
    PopulationMatchingDefaultRecord,
    PopulationMatchingWorkspaceRecord,
    PopulationMissingPolicy,
    PopulationParameterValueKind,
    PopulationSpecParameterRecord,
    PopulationTransformInputAliasRecord,
    PopulationTransformKind,
    PopulationTransformSpecRecord,
    PopulationVariableSetMappingRecord,
    PopulationWorkspaceAuditEventRecord,
    PopulationWorkspaceNoteRecord,
    PopulationWorkspaceNoteTagRecord,
    PopulationWorkspaceStudyRecord,
)
from repositories import population_repo


def list_workspaces(session: Session) -> list[PopulationMatchingWorkspaceRecord]:
    return list(
        session.exec(
            select(PopulationMatchingWorkspaceRecord).order_by(
                PopulationMatchingWorkspaceRecord.name,
                PopulationMatchingWorkspaceRecord.id,
            )
        )
    )


def get_workspace(session: Session, workspace_id: int) -> PopulationMatchingWorkspaceRecord | None:
    return session.get(PopulationMatchingWorkspaceRecord, workspace_id)


def get_workspace_by_external_id(session: Session, external_id: str) -> PopulationMatchingWorkspaceRecord | None:
    return session.exec(
        select(PopulationMatchingWorkspaceRecord).where(PopulationMatchingWorkspaceRecord.external_id == external_id)
    ).first()


def list_workspace_studies(session: Session, workspace_id: int) -> list[PopulationWorkspaceStudyRecord]:
    return list(
        session.exec(
            select(PopulationWorkspaceStudyRecord)
            .where(PopulationWorkspaceStudyRecord.workspace_id == workspace_id)
            .order_by(PopulationWorkspaceStudyRecord.order_index, PopulationWorkspaceStudyRecord.id)
        )
    )


def create_workspace(
    session: Session,
    *,
    name: str,
    source_study_id: int,
    target_study_id: int,
    description: str | None = None,
) -> PopulationMatchingWorkspaceRecord:
    now = datetime.utcnow()
    workspace = PopulationMatchingWorkspaceRecord(
        external_id=_new_external_id("workspace"),
        name=name,
        description=description,
        primary_source_study_id=source_study_id,
        primary_target_study_id=target_study_id,
        created_at=now,
        updated_at=now,
    )
    session.add(workspace)
    session.flush()
    for order, study_id in enumerate((source_study_id, target_study_id)):
        session.add(PopulationWorkspaceStudyRecord(workspace_id=int(workspace.id), study_id=study_id, order_index=order))
    session.add(
        PopulationMatchingDefaultRecord(
            workspace_id=int(workspace.id),
            source_study_id=source_study_id,
            target_study_id=target_study_id,
        )
    )
    session.add(PopulationDiagnosticsRecord(workspace_id=int(workspace.id)))
    add_audit_event(session, int(workspace.id), "create", "Created matching workspace")
    session.commit()
    session.refresh(workspace)
    return workspace


def get_matching_defaults(session: Session, workspace_id: int) -> PopulationMatchingDefaultRecord | None:
    return session.exec(
        select(PopulationMatchingDefaultRecord).where(PopulationMatchingDefaultRecord.workspace_id == workspace_id)
    ).first()


def update_matching_defaults(
    session: Session,
    workspace_id: int,
    *,
    source_study_id: int,
    target_study_id: int,
    k: int,
) -> PopulationMatchingDefaultRecord:
    row = get_matching_defaults(session, workspace_id)
    if row is None:
        row = PopulationMatchingDefaultRecord(workspace_id=workspace_id)
        session.add(row)
    row.source_study_id = source_study_id
    row.target_study_id = target_study_id
    row.k = max(int(k), 1)
    _touch_workspace(session, workspace_id)
    add_audit_event(session, workspace_id, "save", "Updated matching defaults")
    session.commit()
    session.refresh(row)
    return row


def list_mappings(session: Session, workspace_id: int) -> list[PopulationVariableSetMappingRecord]:
    return list(
        session.exec(
            select(PopulationVariableSetMappingRecord)
            .where(PopulationVariableSetMappingRecord.workspace_id == workspace_id)
            .order_by(PopulationVariableSetMappingRecord.created_at, PopulationVariableSetMappingRecord.id)
        )
    )


def list_mapping_inputs(session: Session, mapping_id: int) -> list[PopulationMappingInputRecord]:
    return list(
        session.exec(
            select(PopulationMappingInputRecord)
            .where(PopulationMappingInputRecord.mapping_id == mapping_id)
            .order_by(PopulationMappingInputRecord.side, PopulationMappingInputRecord.order_index)
        )
    )


def list_mapping_transforms(session: Session, mapping_id: int) -> list[PopulationTransformSpecRecord]:
    return list(
        session.exec(
            select(PopulationTransformSpecRecord)
            .where(PopulationTransformSpecRecord.mapping_id == mapping_id)
            .order_by(PopulationTransformSpecRecord.side)
        )
    )


def get_mapping_comparator(session: Session, mapping_id: int) -> PopulationComparatorSpecRecord | None:
    return session.exec(
        select(PopulationComparatorSpecRecord).where(PopulationComparatorSpecRecord.mapping_id == mapping_id)
    ).first()


def list_transform_aliases(session: Session, transform_id: int) -> list[str]:
    rows = session.exec(
        select(PopulationTransformInputAliasRecord)
        .where(PopulationTransformInputAliasRecord.transform_id == transform_id)
        .order_by(PopulationTransformInputAliasRecord.order_index)
    )
    return [row.alias for row in rows]


def create_mapping(
    session: Session,
    *,
    workspace_id: int,
    name: str,
    left_study_id: int,
    right_study_id: int,
    left_inputs: Iterable[dict[str, Any]],
    right_inputs: Iterable[dict[str, Any]],
    left_transform: dict[str, Any],
    right_transform: dict[str, Any],
    comparator: dict[str, Any],
    output_kind,
    weight: float,
    description: str | None = None,
    notes: str | None = None,
) -> PopulationVariableSetMappingRecord:
    row = PopulationVariableSetMappingRecord(
        external_id=_new_external_id("mapping"),
        workspace_id=workspace_id,
        name=name,
        description=description,
        left_study_id=left_study_id,
        right_study_id=right_study_id,
        output_kind=output_kind,
        weight=weight,
        notes=notes,
    )
    session.add(row)
    session.flush()
    _create_mapping_inputs(session, int(row.id), "left", left_inputs)
    _create_mapping_inputs(session, int(row.id), "right", right_inputs)
    _create_transform(session, int(row.id), "left", left_transform)
    _create_transform(session, int(row.id), "right", right_transform)
    _create_comparator(session, int(row.id), comparator)
    _touch_workspace(session, workspace_id)
    add_audit_event(session, workspace_id, "save", f"Added mapping {name}", object_external_id=row.external_id)
    session.commit()
    session.refresh(row)
    return row


def disable_mapping(session: Session, mapping_id: int) -> None:
    mapping = session.get(PopulationVariableSetMappingRecord, mapping_id)
    if mapping is None:
        return
    mapping.status = PopulationMappingStatus.disabled
    _touch_workspace(session, mapping.workspace_id)
    add_audit_event(session, mapping.workspace_id, "disable", f"Disabled mapping {mapping.name}", object_external_id=mapping.external_id)
    session.commit()


def read_parameters(
    session: Session,
    *,
    transform_id: int | None = None,
    comparator_id: int | None = None,
) -> dict[str, Any]:
    statement = select(PopulationSpecParameterRecord).where(PopulationSpecParameterRecord.parent_id == None)  # noqa: E711
    if transform_id is not None:
        statement = statement.where(PopulationSpecParameterRecord.transform_id == transform_id)
    else:
        statement = statement.where(PopulationSpecParameterRecord.comparator_id == comparator_id)
    rows = list(session.exec(statement.order_by(PopulationSpecParameterRecord.order_index, PopulationSpecParameterRecord.id)))
    return {row.key: _read_parameter_node(session, row) for row in rows if row.key is not None}


def list_notes(session: Session, workspace_id: int) -> list[PopulationWorkspaceNoteRecord]:
    return list(
        session.exec(
            select(PopulationWorkspaceNoteRecord)
            .where(PopulationWorkspaceNoteRecord.workspace_id == workspace_id)
            .order_by(PopulationWorkspaceNoteRecord.updated_at.desc(), PopulationWorkspaceNoteRecord.id.desc())
        )
    )


def list_note_tags(session: Session, note_id: int) -> list[str]:
    return [row.tag for row in session.exec(select(PopulationWorkspaceNoteTagRecord).where(PopulationWorkspaceNoteTagRecord.note_id == note_id))]


def add_note(session: Session, workspace_id: int, text: str, tags: Iterable[str] = ()) -> PopulationWorkspaceNoteRecord:
    note = PopulationWorkspaceNoteRecord(external_id=_new_external_id("note"), workspace_id=workspace_id, text=text)
    session.add(note)
    session.flush()
    for tag in tags:
        if tag.strip():
            session.add(PopulationWorkspaceNoteTagRecord(note_id=int(note.id), tag=tag.strip()))
    _touch_workspace(session, workspace_id)
    add_audit_event(session, workspace_id, "note", "Added note", object_external_id=note.external_id)
    session.commit()
    session.refresh(note)
    return note


def add_audit_event(
    session: Session,
    workspace_id: int,
    event_type: str,
    message: str,
    *,
    object_external_id: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> None:
    session.add(
        PopulationWorkspaceAuditEventRecord(
            workspace_id=workspace_id,
            event_type=event_type,
            message=message,
            object_external_id=object_external_id,
            metadata_json=population_repo.json_dump(metadata or {}),
        )
    )


def _create_mapping_inputs(session: Session, mapping_id: int, side: str, inputs: Iterable[dict[str, Any]]) -> None:
    for order, input_spec in enumerate(inputs):
        session.add(
            PopulationMappingInputRecord(
                mapping_id=mapping_id,
                question_id=int(input_spec["question_id"]),
                side=side,
                alias=input_spec.get("alias") or f"{side}_{order + 1}",
                required=bool(input_spec.get("required", True)),
                order_index=order,
            )
        )


def _create_transform(session: Session, mapping_id: int, side: str, payload: dict[str, Any]) -> None:
    row = PopulationTransformSpecRecord(
        mapping_id=mapping_id,
        side=side,
        kind=PopulationTransformKind(payload.get("kind", PopulationTransformKind.identity.value)),
        output_alias=payload.get("output_alias", "value"),
        notes=payload.get("notes"),
    )
    session.add(row)
    session.flush()
    for order, alias in enumerate(payload.get("input_aliases", [])):
        session.add(PopulationTransformInputAliasRecord(transform_id=int(row.id), alias=alias, order_index=order))
    write_parameters(session, transform_id=int(row.id), value=payload.get("parameters", {}))


def _create_comparator(session: Session, mapping_id: int, payload: dict[str, Any]) -> None:
    row = PopulationComparatorSpecRecord(
        mapping_id=mapping_id,
        kind=PopulationComparatorKind(payload.get("kind", PopulationComparatorKind.exact_match.value)),
        missing_policy=PopulationMissingPolicy(payload.get("missing_policy", PopulationMissingPolicy.pairwise_ignore.value)),
        notes=payload.get("notes"),
    )
    session.add(row)
    session.flush()
    write_parameters(session, comparator_id=int(row.id), value=payload.get("parameters", {}))


def write_parameters(
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
            write_parameters(
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
    children = value.items() if isinstance(value, dict) else enumerate(value) if isinstance(value, list) else ()
    for order, child in enumerate(children):
        if isinstance(value, dict):
            child_key, child_value = child
        else:
            _, child_value = child
            child_key = None
        write_parameters(session, value=child_value, parent_id=int(row.id), key=child_key, order_index=order)


def _read_parameter_node(session: Session, row: PopulationSpecParameterRecord) -> Any:
    children = list(
        session.exec(
            select(PopulationSpecParameterRecord)
            .where(PopulationSpecParameterRecord.parent_id == row.id)
            .order_by(PopulationSpecParameterRecord.order_index, PopulationSpecParameterRecord.id)
        )
    )
    if children:
        if all(child.key is None for child in children):
            return [_read_parameter_node(session, child) for child in children]
        return {child.key: _read_parameter_node(session, child) for child in children if child.key is not None}
    if row.value_kind == PopulationParameterValueKind.boolean:
        return row.value_bool
    if row.value_kind == PopulationParameterValueKind.integer:
        return row.value_integer
    if row.value_kind == PopulationParameterValueKind.number:
        return row.value_number
    if row.value_kind == PopulationParameterValueKind.string:
        return row.value_string
    return None


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


def _touch_workspace(session: Session, workspace_id: int) -> None:
    workspace = get_workspace(session, workspace_id)
    if workspace is not None:
        workspace.updated_at = datetime.utcnow()


def _new_external_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex[:12]}"
