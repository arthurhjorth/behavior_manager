from __future__ import annotations

from dataclasses import dataclass

from models import DatasetFieldType, _coerce_dataset_value


@dataclass
class ValidationError:
    message: str


def validate_dataset_name(name: str) -> list[ValidationError]:
    if not name.strip():
        return [ValidationError("Dataset name is required.")]
    return []


def validate_field_payload(name: str, order_index: int, default_raw: str) -> list[ValidationError]:
    errors: list[ValidationError] = []
    if not name.strip():
        errors.append(ValidationError("Field name is required."))
    if order_index < 0:
        errors.append(ValidationError("order_index must be >= 0."))
    if default_raw.strip() == "":
        errors.append(ValidationError("Default value is required."))
    return errors


def parse_field_type(raw: str) -> DatasetFieldType:
    return DatasetFieldType(raw)


def parse_typed_value(field_type: DatasetFieldType, raw_value: str):
    value_int, value_float, value_bool, value_string = _coerce_dataset_value(field_type, raw_value)
    if field_type == DatasetFieldType._int:
        return value_int
    if field_type == DatasetFieldType._float:
        return value_float
    if field_type == DatasetFieldType._bool:
        return value_bool
    return value_string


def typed_value_to_string(field_type: DatasetFieldType, value_row) -> str:
    if field_type == DatasetFieldType._int:
        return str(value_row.value_int)
    if field_type == DatasetFieldType._float:
        return str(value_row.value_float)
    if field_type == DatasetFieldType._bool:
        return "true" if value_row.value_bool else "false"
    return value_row.value_string or ""

