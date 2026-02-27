from __future__ import annotations

from dataclasses import dataclass

from sqlmodel import Session

from models import (
    AdapterLikelihoodMode,
    ConditionOperator,
    ConditionCombinator,
    AdapterType,
    AdapterSetRecord,
    Agent,
    BinaryAdapter,
    Decision,
    LinearAdapter,
    Outcome,
    VarType,
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


def validate_binary_adapter_payload(
    target_outcome_id: int | None,
    multiplier: float,
    likelihood_mode: AdapterLikelihoodMode,
    set_likelihood: float | None,
) -> list[ValidationError]:
    errors: list[ValidationError] = []
    if target_outcome_id is None:
        errors.append(ValidationError("Target outcome is required."))
    if likelihood_mode == AdapterLikelihoodMode.multiply and multiplier <= 0:
        errors.append(ValidationError("Multiplier must be > 0."))
    if likelihood_mode == AdapterLikelihoodMode.set:
        if set_likelihood is None:
            errors.append(ValidationError("Set likelihood is required in set mode."))
        elif set_likelihood < 0:
            errors.append(ValidationError("Set likelihood must be >= 0."))
    return errors


def validate_linear_adapter_payload(
    target_outcome_id: int | None,
    intercept: float,
    min_multiplier: float,
    max_multiplier: float | None,
    likelihood_mode: AdapterLikelihoodMode,
) -> list[ValidationError]:
    errors: list[ValidationError] = []
    if target_outcome_id is None:
        errors.append(ValidationError("Target outcome is required."))
    if max_multiplier is not None and max_multiplier < min_multiplier:
        errors.append(ValidationError("max_multiplier must be >= min_multiplier."))
    if likelihood_mode == AdapterLikelihoodMode.multiply and intercept < 0 and min_multiplier < 0:
        errors.append(ValidationError("At least one lower bound should keep multiplier non-negative."))
    return errors


def validate_coefficient_payload(variable_id: int | None) -> list[ValidationError]:
    if variable_id is None:
        return [ValidationError("Variable is required.")]
    return []


def validate_condition_payload(
    variable_id: int | None,
    operator: ConditionOperator | None,
    raw_value: str,
) -> list[ValidationError]:
    errors: list[ValidationError] = []
    if variable_id is None:
        errors.append(ValidationError("Variable is required."))
    if operator is None:
        errors.append(ValidationError("Operator is required."))
    if not (raw_value or "").strip():
        errors.append(ValidationError("Condition value is required."))
    return errors


def parse_condition_value(var_type: VarType, raw_value: str) -> tuple[int | None, float | None, bool | None]:
    text = (raw_value or "").strip()
    if var_type == VarType._int:
        return int(text), None, None
    if var_type == VarType._float:
        return None, float(text), None
    value = text.lower()
    if value in {"true", "t", "yes", "y", "1"}:
        return None, None, True
    if value in {"false", "f", "no", "n", "0"}:
        return None, None, False
    raise ValueError("Boolean condition values must be true/false (or 1/0).")


def build_runtime_decision(session: Session, decision_id: int) -> Decision:
    decision = decision_repo.get_decision(session, decision_id)
    if decision is None:
        raise ValueError(f"Decision {decision_id} not found")

    outcomes = [
        Outcome(name=row.name, likelihood=row.likelihood if row.likelihood is not None else 0.0)
        for row in decision_repo.list_outcomes(session, decision.id)
    ]
    outcome_name_by_id = {row.id: row.name for row in decision_repo.list_outcomes(session, decision.id)}
    all_variables = decision_repo.list_variables(session)
    variable_name_by_id = {row.id: row.name for row in all_variables}
    variable_type_by_id = {row.id: row.var_type for row in all_variables}

    adapters = []
    for adapter_set in decision_repo.list_adapter_sets(session, decision.id):
        if adapter_set.id is None:
            continue
        set_funcs = _build_chain_funcs(
            session,
            adapter_set,
            variable_name_by_id,
            variable_type_by_id,
        )
        for adapter_row in decision_repo.list_adapters(session, adapter_set_id=int(adapter_set.id)):
            target_name = outcome_name_by_id.get(adapter_row.target_outcome_id)
            if target_name is None:
                raise ValueError(
                    f"Adapter {adapter_row.id} references unknown outcome id {adapter_row.target_outcome_id}"
                )

            if adapter_row.adapter_type == AdapterType.binary:
                adapters.append(
                    BinaryAdapter(
                        target_outcome=target_name,
                        multiplier=adapter_row.multiplier or 1.0,
                        likelihood_mode=adapter_row.likelihood_mode,
                        set_likelihood=adapter_row.set_likelihood,
                        funcs=set_funcs,
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
                    likelihood_mode=adapter_row.likelihood_mode,
                    funcs=set_funcs,
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


def _build_chain_funcs(
    session: Session,
    adapter_set: AdapterSetRecord,
    variable_name_by_id: dict[int | None, str],
    variable_type_by_id: dict[int | None, VarType],
):
    chains = decision_repo.list_chains(session, int(adapter_set.id))
    if not chains:
        return []

    funcs = []
    for chain in chains:
        predicates = decision_repo.list_predicates(session, int(chain.id))
        if not predicates:
            continue
        predicate_funcs = []
        for predicate in predicates:
            variable_name = variable_name_by_id.get(predicate.variable_id)
            if variable_name is None:
                raise ValueError(
                    f"Predicate {predicate.id} references unknown variable id {predicate.variable_id}"
                )
            variable_type = variable_type_by_id.get(predicate.variable_id)
            if variable_type is None:
                raise ValueError(
                    f"Predicate {predicate.id} has no known type for variable id {predicate.variable_id}"
                )
            expected = _expected_condition_value(predicate, variable_type)
            predicate_funcs.append(_make_condition_func(variable_name, predicate.operator, expected))

        funcs.append(_compose_predicates(predicate_funcs, chain.combinator))
    return funcs


def _compose_predicates(predicate_funcs, combinator: ConditionCombinator):
    def _chain(vars_table):
        if not predicate_funcs:
            return True
        results = [fn(vars_table) for fn in predicate_funcs]
        if combinator == ConditionCombinator.any:
            return any(results)
        return all(results)

    return _chain


def _expected_condition_value(condition, variable_type: VarType):
    if variable_type == VarType._int:
        if condition.value_int is None:
            raise ValueError(f"Condition {condition.id} is missing int value")
        return condition.value_int
    if variable_type == VarType._float:
        if condition.value_float is None:
            raise ValueError(f"Condition {condition.id} is missing float value")
        return condition.value_float
    if condition.value_bool is None:
        raise ValueError(f"Condition {condition.id} is missing bool value")
    return condition.value_bool


def _make_condition_func(variable_name: str, operator: ConditionOperator, expected):
    def _fn(vars_table):
        current = vars_table.get_value(variable_name)
        if current is None:
            return False
        if operator == ConditionOperator.eq:
            return current == expected
        if operator == ConditionOperator.ne:
            return current != expected
        if operator == ConditionOperator.gt:
            return float(current) > float(expected)
        if operator == ConditionOperator.gte:
            return float(current) >= float(expected)
        if operator == ConditionOperator.lt:
            return float(current) < float(expected)
        if operator == ConditionOperator.lte:
            return float(current) <= float(expected)
        raise ValueError(f"Unsupported condition operator: {operator}")

    return _fn
