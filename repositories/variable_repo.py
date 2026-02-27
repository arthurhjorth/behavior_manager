from __future__ import annotations

from typing import Any

from sqlmodel import Session, select

from models import LinearCoefficientRecord, PredicateRecord
from models import VarType, VariableRecord, _coerce_value_for_storage
from repositories.decision_repo import ensure_agent


def list_variables(session: Session, agent_id: int | None = None) -> tuple[int, list[VariableRecord]]:
    agent = ensure_agent(session, agent_id=agent_id)
    statement = (
        select(VariableRecord)
        .where(VariableRecord.agent_id == agent.id)
        .order_by(VariableRecord.id)
    )
    return agent.id, list(session.exec(statement))


def get_variable(session: Session, variable_id: int) -> VariableRecord | None:
    return session.get(VariableRecord, variable_id)


def create_variable(
    session: Session,
    *,
    agent_id: int,
    name: str,
    var_type: VarType,
    value: Any,
    is_observer: bool,
    is_turtle: bool,
    is_patch: bool,
    is_link: bool,
    breed: str,
) -> VariableRecord:
    value_int, value_float, value_bool = _coerce_value_for_storage(var_type, value)
    row = VariableRecord(
        agent_id=agent_id,
        name=name,
        var_type=var_type,
        is_observer=is_observer,
        is_turtle=is_turtle,
        is_patch=is_patch,
        is_link=is_link,
        breed=breed,
        value_int=value_int,
        value_float=value_float,
        value_bool=value_bool,
    )
    session.add(row)
    session.commit()
    session.refresh(row)
    return row


def update_variable(
    session: Session,
    *,
    variable_id: int,
    name: str,
    var_type: VarType,
    value: Any,
    is_observer: bool,
    is_turtle: bool,
    is_patch: bool,
    is_link: bool,
    breed: str,
) -> VariableRecord:
    row = session.get(VariableRecord, variable_id)
    if row is None:
        raise ValueError(f"Variable {variable_id} not found")

    value_int, value_float, value_bool = _coerce_value_for_storage(var_type, value)

    row.name = name
    row.var_type = var_type
    row.is_observer = is_observer
    row.is_turtle = is_turtle
    row.is_patch = is_patch
    row.is_link = is_link
    row.breed = breed
    row.value_int = value_int
    row.value_float = value_float
    row.value_bool = value_bool

    session.add(row)
    session.commit()
    session.refresh(row)
    return row


def delete_variable(session: Session, variable_id: int) -> None:
    row = session.get(VariableRecord, variable_id)
    if row is None:
        return

    coeffs = list(
        session.exec(
            select(LinearCoefficientRecord).where(LinearCoefficientRecord.variable_id == variable_id)
        )
    )
    for coeff in coeffs:
        session.delete(coeff)

    conditions = list(
        session.exec(
            select(PredicateRecord).where(PredicateRecord.variable_id == variable_id)
        )
    )
    for condition in conditions:
        session.delete(condition)

    session.delete(row)
    session.commit()
