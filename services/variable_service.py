from __future__ import annotations

from dataclasses import dataclass

from models import VarType, VariableRecord


@dataclass
class ValidationError:
    message: str


def parse_var_type(value: str) -> VarType:
    return VarType(value)


def variable_value_to_string(row: VariableRecord) -> str:
    if row.var_type == VarType._int:
        return '' if row.value_int is None else str(row.value_int)
    if row.var_type == VarType._float:
        return '' if row.value_float is None else str(row.value_float)
    return '' if row.value_bool is None else ('true' if row.value_bool else 'false')


def parse_value(raw_value: str, var_type: VarType):
    text = (raw_value or '').strip()
    if text == '':
        return None

    if var_type == VarType._int:
        return int(text)
    if var_type == VarType._float:
        return float(text)

    value = text.lower()
    if value in {'true', 't', 'yes', 'y', '1'}:
        return True
    if value in {'false', 'f', 'no', 'n', '0'}:
        return False
    raise ValueError('Boolean values must be true/false (or 1/0).')


def validate_variable_payload(name: str, breed: str) -> list[ValidationError]:
    errors: list[ValidationError] = []
    if not name.strip():
        errors.append(ValidationError('Variable name is required.'))
    if len(breed) > 64:
        errors.append(ValidationError('Breed should be <= 64 chars.'))
    return errors
