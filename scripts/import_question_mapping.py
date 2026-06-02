from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from sqlmodel import SQLModel, Session, create_engine

from models import (
    PopulationDataKind,
    PopulationQuestionRecord,
    PopulationQuestionRole,
)
from repositories import population_repo


DEFAULT_MAPPING_PATH = Path("codex_container/question_mapping.json")
DEFAULT_DB_URL = "sqlite:///behavior_manager.db"


def import_question_mapping(
    session: Session,
    mapping_path: Path,
    *,
    replace_existing: bool = False,
) -> dict[str, int]:
    payload = _read_json(mapping_path)
    study = _get_or_create_study(session, payload, mapping_path)
    counts = {"created": 0, "skipped": 0, "updated": 0}

    for item in payload.get("items", []):
        external_id = _required_str(item, "external_id")
        existing = population_repo.get_question_by_external_id(session, external_id)
        if existing is not None:
            if not replace_existing:
                counts["skipped"] += 1
                continue
            _update_question(session, existing, item, study_id=int(study.id))
            counts["updated"] += 1
            continue

        source_ref = population_repo.create_source_ref(session, **_source_ref(item))
        scale = _create_scale(session, item)
        session.add(
            PopulationQuestionRecord(
                external_id=external_id,
                study_id=int(study.id),
                source_ref_id=int(source_ref.id),
                scale_id=int(scale.id) if scale and scale.id is not None else None,
                kind=_enum(PopulationDataKind, item.get("data_kind"), PopulationDataKind.unknown),
                wording=_required_str(item, "wording"),
                short_name=item.get("code"),
                role=_enum(PopulationQuestionRole, item.get("role"), PopulationQuestionRole.unknown),
                constructs_json=population_repo.json_dump(item.get("constructs", [])),
                missing_codes_json=population_repo.json_dump(item.get("missing_codes", [])),
                reverse_scored=bool(item.get("reverse_scored", False)),
                harmonized_variable_id=item.get("harmonized_variable_id"),
                metadata_json=population_repo.json_dump(_question_metadata(item)),
            )
        )
        counts["created"] += 1

    session.commit()
    return counts


def _get_or_create_study(session: Session, payload: dict[str, Any], mapping_path: Path):
    external_id = _required_str(payload, "study_external_id")
    existing = population_repo.get_study_by_external_id(session, external_id)
    if existing is not None:
        return existing

    artifact = _artifact_for_mapping(session, mapping_path)
    source_files = payload.get("source_files", {})
    return population_repo.create_study(
        session,
        external_id=external_id,
        name=payload.get("study_name") or external_id,
        source_file=source_files.get("headers") or str(mapping_path),
        source_sheet=_first_source_sheet(payload),
        source_artifact_id=int(artifact.id) if artifact and artifact.id is not None else None,
        description=payload.get("description"),
        metadata={
            "mapping_file": str(mapping_path),
            "questionnaire_file": source_files.get("questionnaire"),
            "schema_version": payload.get("schema_version"),
            "item_count": payload.get("item_count"),
            "conventions": payload.get("conventions", {}),
        },
    )


def _artifact_for_mapping(session: Session, mapping_path: Path):
    content = mapping_path.read_bytes()
    fingerprint = hashlib.sha256(content).hexdigest()
    existing = population_repo.get_artifact_by_fingerprint(session, fingerprint)
    if existing is not None:
        return existing
    return population_repo.create_artifact(
        session,
        filename=str(mapping_path),
        media_type="application/json",
        fingerprint=fingerprint,
        content=content,
        metadata={"import_kind": "population_question_mapping"},
    )


def _create_scale(session: Session, item: dict[str, Any]):
    scale = item.get("scale")
    options = list(item.get("options") or [])
    if not scale and not options:
        return None

    scale_payload = dict(scale or {})
    scale_options = list(scale_payload.pop("options", []) or [])
    normalized_options = [_option_payload(option) for option in scale_options + options]
    raw_description = scale_payload.get("raw_description")
    if not raw_description and options:
        raw_description = "Answer options from questionnaire."

    return population_repo.create_question_scale(
        session,
        min_value=scale_payload.get("min_value"),
        max_value=scale_payload.get("max_value"),
        min_label=scale_payload.get("min_label"),
        max_label=scale_payload.get("max_label"),
        step=scale_payload.get("step"),
        raw_description=raw_description,
        options=normalized_options,
    )


def _update_question(session: Session, row: PopulationQuestionRecord, item: dict[str, Any], *, study_id: int) -> None:
    source_ref = population_repo.create_source_ref(session, **_source_ref(item))
    scale = _create_scale(session, item)
    row.study_id = study_id
    row.source_ref_id = int(source_ref.id)
    row.scale_id = int(scale.id) if scale and scale.id is not None else None
    row.kind = _enum(PopulationDataKind, item.get("data_kind"), PopulationDataKind.unknown)
    row.wording = _required_str(item, "wording")
    row.short_name = item.get("code")
    row.role = _enum(PopulationQuestionRole, item.get("role"), PopulationQuestionRole.unknown)
    row.constructs_json = population_repo.json_dump(item.get("constructs", []))
    row.missing_codes_json = population_repo.json_dump(item.get("missing_codes", []))
    row.reverse_scored = bool(item.get("reverse_scored", False))
    row.harmonized_variable_id = item.get("harmonized_variable_id")
    row.metadata_json = population_repo.json_dump(_question_metadata(item))
    session.add(row)


def _question_metadata(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "code": item.get("code"),
        "parent_code": item.get("parent_code"),
        "source_type": item.get("source_type"),
        "question_text": item.get("question_text"),
        "item_text": item.get("item_text"),
        "constraints": item.get("constraints", {}),
        "source": item.get("source", {}),
        "source_ref": item.get("source_ref", {}),
        "mapping_metadata": item.get("metadata", {}),
        "notes": item.get("notes", ""),
    }


def _source_ref(item: dict[str, Any]) -> dict[str, Any]:
    ref = item.get("source_ref") or {}
    return {
        "file_path": _required_str(ref, "file_path"),
        "sheet_name": ref.get("sheet_name"),
        "row_index": ref.get("row_index"),
        "column_index": ref.get("column_index"),
        "column_name": ref.get("column_name") or item.get("code"),
    }


def _option_payload(option: dict[str, Any]) -> dict[str, Any]:
    return {
        "value": option.get("value"),
        "label": option.get("label"),
        "order": option.get("order") or option.get("order_index"),
        "is_missing": bool(option.get("is_missing", False)),
    }


def _enum(enum_type, value: Any, default):
    try:
        return enum_type(value)
    except (TypeError, ValueError):
        return default


def _first_source_sheet(payload: dict[str, Any]) -> str | None:
    for item in payload.get("items", []):
        source_ref = item.get("source_ref") or {}
        if source_ref.get("sheet_name"):
            return source_ref["sheet_name"]
    return None


def _required_str(mapping: dict[str, Any], key: str) -> str:
    value = mapping.get(key)
    if value is None or str(value).strip() == "":
        raise ValueError(f"Missing required field: {key}")
    return str(value)


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> None:
    parser = argparse.ArgumentParser(description="Import a column-level population question mapping into the database.")
    parser.add_argument("mapping_path", type=Path, nargs="?", default=DEFAULT_MAPPING_PATH)
    parser.add_argument("--db-url", default=DEFAULT_DB_URL)
    parser.add_argument("--replace-existing", action="store_true")
    args = parser.parse_args()

    engine = create_engine(args.db_url)
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        counts = import_question_mapping(session, args.mapping_path, replace_existing=args.replace_existing)
    print(counts)


if __name__ == "__main__":
    main()
