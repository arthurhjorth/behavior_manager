from __future__ import annotations

from sqlmodel import Session, select

from models import (
    AdapterLikelihoodMode,
    AdapterRecord,
    AdapterSetRecord,
    AdapterType,
    AgentRecord,
    ConditionChainRecord,
    ConditionCombinator,
    ConditionOperator,
    ContextRecord,
    DecisionRecord,
    LinearCoefficientRecord,
    OutcomeRecord,
    PredicateRecord,
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


def list_decisions(session: Session) -> list[DecisionRecord]:
    return list(session.exec(select(DecisionRecord).order_by(DecisionRecord.id)))


def list_contexts(session: Session) -> list[ContextRecord]:
    return list(session.exec(select(ContextRecord).order_by(ContextRecord.name, ContextRecord.id)))


def get_context(session: Session, context_id: int) -> ContextRecord | None:
    return session.get(ContextRecord, context_id)


def create_context(session: Session, name: str) -> ContextRecord:
    row = ContextRecord(name=name)
    session.add(row)
    session.commit()
    session.refresh(row)
    return row


def delete_context(session: Session, context_id: int) -> None:
    row = session.get(ContextRecord, context_id)
    if row is None:
        return

    for decision in list(session.exec(select(DecisionRecord).order_by(DecisionRecord.id))):
        if row in decision.contexts:
            decision.contexts = [ctx for ctx in decision.contexts if ctx.id != context_id]
            session.add(decision)

    session.delete(row)
    session.commit()


def get_decision(session: Session, decision_id: int) -> DecisionRecord | None:
    return session.get(DecisionRecord, decision_id)


def create_decision(
    session: Session,
    name: str,
    description: str,
    context_ids: list[int] | None = None,
) -> DecisionRecord:
    row = DecisionRecord(name=name, description=description)
    if context_ids:
        contexts = list(
            session.exec(select(ContextRecord).where(ContextRecord.id.in_(context_ids)))
        )
        row.contexts = contexts
    session.add(row)
    session.commit()
    session.refresh(row)
    return row


def update_decision(
    session: Session,
    decision_id: int,
    name: str,
    description: str,
    context_ids: list[int] | None = None,
) -> DecisionRecord:
    row = session.get(DecisionRecord, decision_id)
    if row is None:
        raise ValueError(f"Decision {decision_id} not found")
    row.name = name
    row.description = description
    if context_ids:
        contexts = list(
            session.exec(select(ContextRecord).where(ContextRecord.id.in_(context_ids)))
        )
        row.contexts = contexts
    else:
        row.contexts = []
    session.add(row)
    session.commit()
    session.refresh(row)
    return row


def delete_decision(session: Session, decision_id: int) -> None:
    row = session.get(DecisionRecord, decision_id)
    if row is None:
        return

    for adapter_set in list_adapter_sets(session, decision_id):
        delete_adapter_set(session, int(adapter_set.id))
    for outcome in list_outcomes(session, decision_id):
        session.delete(outcome)

    session.delete(row)
    session.commit()


def list_outcomes(session: Session, decision_id: int) -> list[OutcomeRecord]:
    statement = select(OutcomeRecord).where(OutcomeRecord.decision_id == decision_id).order_by(OutcomeRecord.id)
    return list(session.exec(statement))


def create_outcome(session: Session, decision_id: int, name: str, likelihood: float | None = None) -> OutcomeRecord:
    row = OutcomeRecord(decision_id=decision_id, name=name, likelihood=likelihood)
    session.add(row)
    session.commit()
    session.refresh(row)
    return row


def update_outcome(session: Session, outcome_id: int, name: str, likelihood: float | None = None) -> OutcomeRecord:
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
    row = session.get(OutcomeRecord, outcome_id)
    if row is None:
        return

    statement = select(AdapterRecord).where(AdapterRecord.target_outcome_id == outcome_id)
    for effect in list(session.exec(statement)):
        delete_adapter(session, int(effect.id))

    session.delete(row)
    session.commit()


# Adapter Sets

def list_adapter_sets(session: Session, decision_id: int) -> list[AdapterSetRecord]:
    statement = select(AdapterSetRecord).where(AdapterSetRecord.decision_id == decision_id).order_by(
        AdapterSetRecord.order_index,
        AdapterSetRecord.id,
    )
    return list(session.exec(statement))


def get_adapter_set(session: Session, adapter_set_id: int) -> AdapterSetRecord | None:
    return session.get(AdapterSetRecord, adapter_set_id)


def create_adapter_set(
    session: Session,
    decision_id: int,
    name: str = "Rule Set",
    order_index: int = 0,
) -> AdapterSetRecord:
    row = AdapterSetRecord(decision_id=decision_id, name=name, order_index=order_index)
    session.add(row)
    session.commit()
    session.refresh(row)
    ensure_default_chain(session, int(row.id))
    return row


def update_adapter_set(
    session: Session,
    adapter_set_id: int,
    name: str,
    order_index: int,
) -> AdapterSetRecord:
    row = session.get(AdapterSetRecord, adapter_set_id)
    if row is None:
        raise ValueError(f"Adapter set {adapter_set_id} not found")
    row.name = name
    row.order_index = order_index
    session.add(row)
    session.commit()
    session.refresh(row)
    return row


def delete_adapter_set(session: Session, adapter_set_id: int) -> None:
    row = session.get(AdapterSetRecord, adapter_set_id)
    if row is None:
        return

    for effect in list_adapters(session, adapter_set_id=adapter_set_id):
        delete_adapter(session, int(effect.id))
    for chain in list_chains(session, adapter_set_id):
        delete_chain(session, int(chain.id), commit=False)

    session.delete(row)
    session.commit()


# Effects (AdapterRecord)

def list_adapters(
    session: Session,
    decision_id: int | None = None,
    adapter_set_id: int | None = None,
) -> list[AdapterRecord]:
    statement = select(AdapterRecord)
    if adapter_set_id is not None:
        statement = statement.where(AdapterRecord.adapter_set_id == adapter_set_id)
    elif decision_id is not None:
        statement = (
            statement.join(AdapterSetRecord, AdapterSetRecord.id == AdapterRecord.adapter_set_id)
            .where(AdapterSetRecord.decision_id == decision_id)
        )
    statement = statement.order_by(AdapterRecord.order_index, AdapterRecord.id)
    return list(session.exec(statement))


def get_adapter(session: Session, adapter_id: int) -> AdapterRecord | None:
    return session.get(AdapterRecord, adapter_id)


def _resolve_adapter_set_id(
    session: Session,
    *,
    decision_id: int | None,
    adapter_set_id: int | None,
) -> int:
    if adapter_set_id is not None:
        return adapter_set_id
    if decision_id is None:
        raise ValueError("Either decision_id or adapter_set_id is required.")
    sets = list_adapter_sets(session, decision_id)
    if sets:
        return int(sets[0].id)
    created = create_adapter_set(session, decision_id=decision_id, name="Default Rule Set", order_index=0)
    return int(created.id)


def create_binary_adapter(
    session: Session,
    decision_id: int | None = None,
    adapter_set_id: int | None = None,
    target_outcome_id: int = 0,
    multiplier: float = 1.0,
    likelihood_mode: AdapterLikelihoodMode = AdapterLikelihoodMode.multiply,
    set_likelihood: float | None = None,
    add_points: float | None = None,
    order_index: int = 0,
) -> AdapterRecord:
    resolved_set_id = _resolve_adapter_set_id(session, decision_id=decision_id, adapter_set_id=adapter_set_id)
    row = AdapterRecord(
        adapter_set_id=resolved_set_id,
        target_outcome_id=target_outcome_id,
        adapter_type=AdapterType.binary,
        likelihood_mode=likelihood_mode,
        multiplier=multiplier,
        set_likelihood=set_likelihood,
        add_points=add_points,
        order_index=order_index,
    )
    session.add(row)
    session.commit()
    session.refresh(row)
    return row


def create_linear_adapter(
    session: Session,
    decision_id: int | None = None,
    adapter_set_id: int | None = None,
    target_outcome_id: int = 0,
    intercept: float = 1.0,
    min_multiplier: float = 0.0,
    max_multiplier: float | None = None,
    likelihood_mode: AdapterLikelihoodMode = AdapterLikelihoodMode.multiply,
    order_index: int = 0,
) -> AdapterRecord:
    resolved_set_id = _resolve_adapter_set_id(session, decision_id=decision_id, adapter_set_id=adapter_set_id)
    row = AdapterRecord(
        adapter_set_id=resolved_set_id,
        target_outcome_id=target_outcome_id,
        adapter_type=AdapterType.linear,
        likelihood_mode=likelihood_mode,
        intercept=intercept,
        min_multiplier=min_multiplier,
        max_multiplier=max_multiplier,
        order_index=order_index,
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
    likelihood_mode: AdapterLikelihoodMode = AdapterLikelihoodMode.multiply,
    set_likelihood: float | None = None,
    add_points: float | None = None,
    order_index: int = 0,
) -> AdapterRecord:
    row = session.get(AdapterRecord, adapter_id)
    if row is None:
        raise ValueError(f"Adapter effect {adapter_id} not found")
    row.adapter_type = AdapterType.binary
    row.target_outcome_id = target_outcome_id
    row.likelihood_mode = likelihood_mode
    row.multiplier = multiplier
    row.set_likelihood = set_likelihood
    row.add_points = add_points
    row.intercept = None
    row.min_multiplier = None
    row.max_multiplier = None
    row.order_index = order_index
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
    likelihood_mode: AdapterLikelihoodMode = AdapterLikelihoodMode.multiply,
    order_index: int = 0,
) -> AdapterRecord:
    row = session.get(AdapterRecord, adapter_id)
    if row is None:
        raise ValueError(f"Adapter effect {adapter_id} not found")
    row.adapter_type = AdapterType.linear
    row.target_outcome_id = target_outcome_id
    row.likelihood_mode = likelihood_mode
    row.multiplier = None
    row.set_likelihood = None
    row.add_points = None
    row.intercept = intercept
    row.min_multiplier = min_multiplier
    row.max_multiplier = max_multiplier
    row.order_index = order_index
    session.add(row)
    session.commit()
    session.refresh(row)
    return row


def delete_adapter(session: Session, adapter_id: int) -> None:
    row = session.get(AdapterRecord, adapter_id)
    if row is None:
        return
    for coefficient in list_coefficients(session, adapter_id):
        session.delete(coefficient)
    session.delete(row)
    session.commit()


def list_coefficients(session: Session, adapter_id: int) -> list[LinearCoefficientRecord]:
    statement = select(LinearCoefficientRecord).where(LinearCoefficientRecord.adapter_id == adapter_id).order_by(
        LinearCoefficientRecord.id
    )
    return list(session.exec(statement))


def create_coefficient(session: Session, adapter_id: int, variable_id: int, coefficient: float) -> LinearCoefficientRecord:
    row = LinearCoefficientRecord(adapter_id=adapter_id, variable_id=variable_id, coefficient=coefficient)
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


def list_variables(session: Session, agent_id: int | None = None) -> list[VariableRecord]:
    statement = select(VariableRecord).order_by(VariableRecord.id)
    if agent_id is not None:
        statement = statement.where(VariableRecord.agent_id == agent_id)
    return list(session.exec(statement))


# Predicate groups/chains

def list_chains(session: Session, adapter_set_id: int) -> list[ConditionChainRecord]:
    statement = select(ConditionChainRecord).where(ConditionChainRecord.adapter_set_id == adapter_set_id).order_by(
        ConditionChainRecord.order_index,
        ConditionChainRecord.id,
    )
    return list(session.exec(statement))


def get_chain(session: Session, chain_id: int) -> ConditionChainRecord | None:
    return session.get(ConditionChainRecord, chain_id)


def ensure_default_chain(session: Session, adapter_set_id: int) -> ConditionChainRecord:
    chains = list_chains(session, adapter_set_id)
    if chains:
        return chains[0]
    row = ConditionChainRecord(
        adapter_set_id=adapter_set_id,
        name="Default Group",
        combinator=ConditionCombinator.all,
        order_index=0,
    )
    session.add(row)
    session.commit()
    session.refresh(row)
    return row


def create_chain(
    session: Session,
    adapter_set_id: int,
    name: str,
    combinator: ConditionCombinator,
    order_index: int = 0,
) -> ConditionChainRecord:
    row = ConditionChainRecord(
        adapter_set_id=adapter_set_id,
        name=name,
        combinator=combinator,
        order_index=order_index,
    )
    session.add(row)
    session.commit()
    session.refresh(row)
    return row


def update_chain(
    session: Session,
    chain_id: int,
    name: str,
    combinator: ConditionCombinator,
    order_index: int,
) -> ConditionChainRecord:
    row = session.get(ConditionChainRecord, chain_id)
    if row is None:
        raise ValueError(f"Chain {chain_id} not found")
    row.name = name
    row.combinator = combinator
    row.order_index = order_index
    session.add(row)
    session.commit()
    session.refresh(row)
    return row


def delete_chain(session: Session, chain_id: int, *, commit: bool = True) -> None:
    row = session.get(ConditionChainRecord, chain_id)
    if row is None:
        return
    for predicate in list_predicates(session, chain_id):
        session.delete(predicate)
    session.delete(row)
    if commit:
        session.commit()


def list_predicates(session: Session, chain_id: int) -> list[PredicateRecord]:
    statement = select(PredicateRecord).where(PredicateRecord.chain_id == chain_id).order_by(
        PredicateRecord.order_index,
        PredicateRecord.id,
    )
    return list(session.exec(statement))


def create_predicate(
    session: Session,
    chain_id: int,
    variable_id: int,
    operator: ConditionOperator,
    value_int: int | None = None,
    value_float: float | None = None,
    value_bool: bool | None = None,
    order_index: int = 0,
) -> PredicateRecord:
    row = PredicateRecord(
        chain_id=chain_id,
        variable_id=variable_id,
        operator=operator,
        value_int=value_int,
        value_float=value_float,
        value_bool=value_bool,
        order_index=order_index,
    )
    session.add(row)
    session.commit()
    session.refresh(row)
    return row


def update_predicate(
    session: Session,
    predicate_id: int,
    variable_id: int,
    operator: ConditionOperator,
    value_int: int | None = None,
    value_float: float | None = None,
    value_bool: bool | None = None,
    order_index: int = 0,
) -> PredicateRecord:
    row = session.get(PredicateRecord, predicate_id)
    if row is None:
        raise ValueError(f"Predicate {predicate_id} not found")
    row.variable_id = variable_id
    row.operator = operator
    row.value_int = value_int
    row.value_float = value_float
    row.value_bool = value_bool
    row.order_index = order_index
    session.add(row)
    session.commit()
    session.refresh(row)
    return row


def delete_predicate(session: Session, predicate_id: int) -> None:
    row = session.get(PredicateRecord, predicate_id)
    if row is None:
        return
    session.delete(row)
    session.commit()


# Compatibility with previous condition API, mapped to first/default group of an adapter set.

def _adapter_to_set_id(session: Session, adapter_id: int) -> int:
    effect = session.get(AdapterRecord, adapter_id)
    if effect is not None:
        return int(effect.adapter_set_id)
    adapter_set = session.get(AdapterSetRecord, adapter_id)
    if adapter_set is not None:
        return int(adapter_set.id)
    raise ValueError(f"Adapter effect/set {adapter_id} not found")


def list_conditions(session: Session, adapter_id: int) -> list[PredicateRecord]:
    set_id = _adapter_to_set_id(session, adapter_id)
    chain = ensure_default_chain(session, set_id)
    return list_predicates(session, int(chain.id))


def create_condition(
    session: Session,
    adapter_id: int,
    variable_id: int,
    operator: ConditionOperator,
    value_int: int | None = None,
    value_float: float | None = None,
    value_bool: bool | None = None,
) -> PredicateRecord:
    set_id = _adapter_to_set_id(session, adapter_id)
    chain = ensure_default_chain(session, set_id)
    return create_predicate(
        session,
        chain_id=int(chain.id),
        variable_id=variable_id,
        operator=operator,
        value_int=value_int,
        value_float=value_float,
        value_bool=value_bool,
    )


def update_condition(
    session: Session,
    condition_id: int,
    variable_id: int,
    operator: ConditionOperator,
    value_int: int | None = None,
    value_float: float | None = None,
    value_bool: bool | None = None,
) -> PredicateRecord:
    return update_predicate(
        session,
        predicate_id=condition_id,
        variable_id=variable_id,
        operator=operator,
        value_int=value_int,
        value_float=value_float,
        value_bool=value_bool,
    )


def delete_condition(session: Session, condition_id: int) -> None:
    delete_predicate(session, condition_id)
