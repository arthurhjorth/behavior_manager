from __future__ import annotations

from sqlmodel import Session, select

from models import (
    AdapterRecord,
    AdapterType,
    AgentRecord,
    DecisionRecord,
    LinearCoefficientRecord,
    OutcomeRecord,
    VariableRecord,
)


def ensure_agent(session: Session, agent_id: int | None = None, default_name: str = "default") -> AgentRecord:
    if agent_id is not None:
        agent = session.get(AgentRecord, agent_id)
        if agent is None:
            raise ValueError(f"Agent {agent_id} not found")
        return agent

    existing = session.exec(select(AgentRecord).order_by(AgentRecord.id)).first()
    if existing is not None:
        return existing

    agent = AgentRecord(name=default_name)
    session.add(agent)
    session.commit()
    session.refresh(agent)
    return agent


def list_decisions(session: Session, agent_id: int | None = None) -> list[DecisionRecord]:
    statement = select(DecisionRecord).order_by(DecisionRecord.id)
    if agent_id is not None:
        statement = statement.where(DecisionRecord.agent_id == agent_id)
    return list(session.exec(statement))


def get_decision(session: Session, decision_id: int) -> DecisionRecord | None:
    return session.get(DecisionRecord, decision_id)


def create_decision(session: Session, agent_id: int, name: str, description: str) -> DecisionRecord:
    record = DecisionRecord(agent_id=agent_id, name=name, description=description)
    session.add(record)
    session.commit()
    session.refresh(record)
    return record


def update_decision(session: Session, decision_id: int, name: str, description: str) -> DecisionRecord:
    record = session.get(DecisionRecord, decision_id)
    if record is None:
        raise ValueError(f"Decision {decision_id} not found")
    record.name = name
    record.description = description
    session.add(record)
    session.commit()
    session.refresh(record)
    return record


def delete_decision(session: Session, decision_id: int) -> None:
    decision = session.get(DecisionRecord, decision_id)
    if decision is None:
        return

    adapters = list_adapters(session, decision_id)
    for adapter in adapters:
        delete_adapter(session, int(adapter.id))

    outcomes = list_outcomes(session, decision_id)
    for outcome in outcomes:
        session.delete(outcome)

    session.delete(decision)
    session.commit()


def list_outcomes(session: Session, decision_id: int) -> list[OutcomeRecord]:
    statement = (
        select(OutcomeRecord)
        .where(OutcomeRecord.decision_id == decision_id)
        .order_by(OutcomeRecord.id)
    )
    return list(session.exec(statement))


def create_outcome(
    session: Session,
    decision_id: int,
    name: str,
    likelihood: float | None = None,
) -> OutcomeRecord:
    row = OutcomeRecord(decision_id=decision_id, name=name, likelihood=likelihood)
    session.add(row)
    session.commit()
    session.refresh(row)
    return row


def update_outcome(
    session: Session,
    outcome_id: int,
    name: str,
    likelihood: float | None = None,
) -> OutcomeRecord:
    row = session.get(OutcomeRecord, outcome_id)
    if row is None:
        raise ValueError(f"Outcome {outcome_id} not found")
    row.name = name
    row.likelihood = likelihood
    session.add(row)
    session.commit()
    session.refresh(row)
    return row


def delete_outcome(session: Session, outcome_id: int) -> None:
    outcome = session.get(OutcomeRecord, outcome_id)
    if outcome is None:
        return

    statement = select(AdapterRecord).where(AdapterRecord.target_outcome_id == outcome_id)
    adapters = list(session.exec(statement))
    for adapter in adapters:
        delete_adapter(session, int(adapter.id))

    session.delete(outcome)
    session.commit()


def list_adapters(session: Session, decision_id: int) -> list[AdapterRecord]:
    statement = (
        select(AdapterRecord)
        .where(AdapterRecord.decision_id == decision_id)
        .order_by(AdapterRecord.id)
    )
    return list(session.exec(statement))


def get_adapter(session: Session, adapter_id: int) -> AdapterRecord | None:
    return session.get(AdapterRecord, adapter_id)


def create_binary_adapter(
    session: Session,
    decision_id: int,
    target_outcome_id: int,
    multiplier: float,
) -> AdapterRecord:
    row = AdapterRecord(
        decision_id=decision_id,
        target_outcome_id=target_outcome_id,
        adapter_type=AdapterType.binary,
        multiplier=multiplier,
    )
    session.add(row)
    session.commit()
    session.refresh(row)
    return row


def create_linear_adapter(
    session: Session,
    decision_id: int,
    target_outcome_id: int,
    intercept: float,
    min_multiplier: float,
    max_multiplier: float | None,
) -> AdapterRecord:
    row = AdapterRecord(
        decision_id=decision_id,
        target_outcome_id=target_outcome_id,
        adapter_type=AdapterType.linear,
        intercept=intercept,
        min_multiplier=min_multiplier,
        max_multiplier=max_multiplier,
    )
    session.add(row)
    session.commit()
    session.refresh(row)
    return row


def update_binary_adapter(
    session: Session,
    adapter_id: int,
    target_outcome_id: int,
    multiplier: float,
) -> AdapterRecord:
    row = session.get(AdapterRecord, adapter_id)
    if row is None:
        raise ValueError(f"Adapter {adapter_id} not found")
    row.adapter_type = AdapterType.binary
    row.target_outcome_id = target_outcome_id
    row.multiplier = multiplier
    row.intercept = None
    row.min_multiplier = None
    row.max_multiplier = None
    session.add(row)
    session.commit()
    session.refresh(row)
    return row


def update_linear_adapter(
    session: Session,
    adapter_id: int,
    target_outcome_id: int,
    intercept: float,
    min_multiplier: float,
    max_multiplier: float | None,
) -> AdapterRecord:
    row = session.get(AdapterRecord, adapter_id)
    if row is None:
        raise ValueError(f"Adapter {adapter_id} not found")
    row.adapter_type = AdapterType.linear
    row.target_outcome_id = target_outcome_id
    row.multiplier = None
    row.intercept = intercept
    row.min_multiplier = min_multiplier
    row.max_multiplier = max_multiplier
    session.add(row)
    session.commit()
    session.refresh(row)
    return row


def delete_adapter(session: Session, adapter_id: int) -> None:
    adapter = session.get(AdapterRecord, adapter_id)
    if adapter is None:
        return

    coeffs = list_coefficients(session, adapter_id)
    for coeff in coeffs:
        session.delete(coeff)

    session.delete(adapter)
    session.commit()


def list_coefficients(session: Session, adapter_id: int) -> list[LinearCoefficientRecord]:
    statement = (
        select(LinearCoefficientRecord)
        .where(LinearCoefficientRecord.adapter_id == adapter_id)
        .order_by(LinearCoefficientRecord.id)
    )
    return list(session.exec(statement))


def create_coefficient(
    session: Session,
    adapter_id: int,
    variable_id: int,
    coefficient: float,
) -> LinearCoefficientRecord:
    row = LinearCoefficientRecord(
        adapter_id=adapter_id,
        variable_id=variable_id,
        coefficient=coefficient,
    )
    session.add(row)
    session.commit()
    session.refresh(row)
    return row


def update_coefficient(
    session: Session,
    coefficient_id: int,
    variable_id: int,
    coefficient: float,
) -> LinearCoefficientRecord:
    row = session.get(LinearCoefficientRecord, coefficient_id)
    if row is None:
        raise ValueError(f"Coefficient {coefficient_id} not found")
    row.variable_id = variable_id
    row.coefficient = coefficient
    session.add(row)
    session.commit()
    session.refresh(row)
    return row


def delete_coefficient(session: Session, coefficient_id: int) -> None:
    row = session.get(LinearCoefficientRecord, coefficient_id)
    if row is None:
        return
    session.delete(row)
    session.commit()


def list_variables(session: Session, agent_id: int) -> list[VariableRecord]:
    statement = (
        select(VariableRecord)
        .where(VariableRecord.agent_id == agent_id)
        .order_by(VariableRecord.id)
    )
    return list(session.exec(statement))
