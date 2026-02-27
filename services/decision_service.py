from __future__ import annotations

from dataclasses import dataclass

from sqlmodel import Session

from models import (
    AdapterType,
    Agent,
    BinaryAdapter,
    Decision,
    LinearAdapter,
    Outcome,
)
from repositories import decision_repo


@dataclass
class ValidationError:
    message: str


def validate_decision_payload(name: str, description: str) -> list[ValidationError]:
    errors: list[ValidationError] = []
    if not name.strip():
        errors.append(ValidationError("Decision name is required."))
    if not description.strip():
        errors.append(ValidationError("Decision description is required."))
    return errors


def validate_outcome_payload(name: str, likelihood: float | None) -> list[ValidationError]:
    errors: list[ValidationError] = []
    if not name.strip():
        errors.append(ValidationError("Outcome name is required."))
    if likelihood is not None and likelihood < 0:
        errors.append(ValidationError("Likelihood must be >= 0."))
    return errors


def validate_binary_adapter_payload(target_outcome_id: int | None, multiplier: float) -> list[ValidationError]:
    errors: list[ValidationError] = []
    if target_outcome_id is None:
        errors.append(ValidationError("Target outcome is required."))
    if multiplier <= 0:
        errors.append(ValidationError("Multiplier must be > 0."))
    return errors


def validate_linear_adapter_payload(
    target_outcome_id: int | None,
    intercept: float,
    min_multiplier: float,
    max_multiplier: float | None,
) -> list[ValidationError]:
    errors: list[ValidationError] = []
    if target_outcome_id is None:
        errors.append(ValidationError("Target outcome is required."))
    if max_multiplier is not None and max_multiplier < min_multiplier:
        errors.append(ValidationError("max_multiplier must be >= min_multiplier."))
    if intercept < 0 and min_multiplier < 0:
        errors.append(ValidationError("At least one lower bound should keep multiplier non-negative."))
    return errors


def validate_coefficient_payload(variable_id: int | None) -> list[ValidationError]:
    if variable_id is None:
        return [ValidationError("Variable is required.")]
    return []


def build_runtime_decision(session: Session, decision_id: int) -> Decision:
    decision = decision_repo.get_decision(session, decision_id)
    if decision is None:
        raise ValueError(f"Decision {decision_id} not found")

    outcomes = [
        Outcome(name=row.name, likelihood=row.likelihood if row.likelihood is not None else 0.0)
        for row in decision_repo.list_outcomes(session, decision.id)
    ]
    outcome_name_by_id = {row.id: row.name for row in decision_repo.list_outcomes(session, decision.id)}
    variable_name_by_id = {
        row.id: row.name
        for row in decision_repo.list_variables(session, decision.agent_id)
    }

    adapters = []
    for adapter_row in decision_repo.list_adapters(session, decision.id):
        target_name = outcome_name_by_id.get(adapter_row.target_outcome_id)
        if target_name is None:
            raise ValueError(f"Adapter {adapter_row.id} references unknown outcome id {adapter_row.target_outcome_id}")

        if adapter_row.adapter_type == AdapterType.binary:
            adapters.append(
                BinaryAdapter(
                    target_outcome=target_name,
                    multiplier=adapter_row.multiplier or 1.0,
                )
            )
            continue

        coeffs = {}
        for c in decision_repo.list_coefficients(session, adapter_row.id):
            variable_name = variable_name_by_id.get(c.variable_id)
            if variable_name is None:
                raise ValueError(f"Coefficient {c.id} references unknown variable id {c.variable_id}")
            coeffs[variable_name] = c.coefficient
        adapters.append(
            LinearAdapter(
                target_outcome=target_name,
                intercept=adapter_row.intercept or 1.0,
                coefficients=coeffs,
                min_multiplier=adapter_row.min_multiplier or 0.0,
                max_multiplier=adapter_row.max_multiplier,
            )
        )

    return Decision(
        name=decision.name,
        description=decision.description,
        outcomes=outcomes,
        adapters=adapters,
    )


def run_runtime_decision(session: Session, decision_id: int) -> list[Outcome]:
    runtime = build_runtime_decision(session, decision_id)
    agent = Agent()
    return agent.run_decision(runtime)
