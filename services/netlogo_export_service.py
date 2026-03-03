from __future__ import annotations

import re

from sqlmodel import Session

from models import AdapterLikelihoodMode, AdapterType, ConditionOperator
from repositories import decision_repo


def export_decision_reporter(session: Session, decision_id: int) -> str:
    decision = decision_repo.get_decision(session, decision_id)
    if decision is None:
        raise ValueError(f'Decision {decision_id} not found')

    outcomes = decision_repo.list_outcomes(session, decision_id)
    if not outcomes:
        raise ValueError('Decision has no outcomes.')

    variables = decision_repo.list_variables(session)
    variable_name_by_id = {int(variable.id): variable.name for variable in variables if variable.id is not None}

    reporter_name = _sanitize_identifier(decision.name)
    outcome_var_names = _outcome_var_names([outcome.name for outcome in outcomes])
    outcome_name_by_id = {int(outcome.id): outcome.name for outcome in outcomes if outcome.id is not None}

    lines: list[str] = []
    lines.append(f'to-report {reporter_name}')

    for outcome in outcomes:
        out_var = outcome_var_names[outcome.name]
        initial = float(outcome.likelihood) if outcome.likelihood is not None else 0.0
        lines.append(f'  let {out_var} {_fmt(initial)}')

    step_index = 0
    for adapter_set in decision_repo.list_adapter_sets(session, decision_id):
        set_id = int(adapter_set.id)
        condition_expr = _adapter_set_condition_expr(session, set_id, variable_name_by_id)
        effects = decision_repo.list_adapters(session, adapter_set_id=set_id)
        if not effects:
            continue

        if condition_expr is None:
            for effect in effects:
                step_index += 1
                lines.extend(_effect_lines(effect, step_index, outcome_var_names, outcome_name_by_id, session))
            continue

        lines.append(f'  if {condition_expr} [')
        for effect in effects:
            step_index += 1
            effect_lines = _effect_lines(effect, step_index, outcome_var_names, outcome_name_by_id, session)
            for line in effect_lines:
                lines.append(f'    {line}')
        lines.append('  ]')

    total_expr = ' + '.join(
        f'(max list 0 {outcome_var_names[outcome.name]})'
        for outcome in outcomes
    )
    lines.append(f'  let __total ({total_expr})')
    lines.append('  ifelse __total = 0 [')
    uniform = _fmt(1.0 / len(outcomes))
    lines.append(f'    report (list {" ".join(f"(list { _quote(outcome.name) } {uniform})" for outcome in outcomes)})')
    lines.append('  ] [')
    report_items = ' '.join(
        f'(list {_quote(outcome.name)} ((max list 0 {outcome_var_names[outcome.name]}) / __total))'
        for outcome in outcomes
    )
    lines.append(f'    report (list {report_items})')
    lines.append('  ]')
    lines.append('end')
    return '\n'.join(lines)


def _adapter_set_condition_expr(session: Session, adapter_set_id: int, variable_name_by_id: dict[int, str]) -> str | None:
    chains = decision_repo.list_chains(session, adapter_set_id)
    group_exprs: list[str] = []
    for chain in chains:
        predicates = decision_repo.list_predicates(session, int(chain.id))
        if not predicates:
            continue
        bits: list[str] = []
        for predicate in predicates:
            variable_name = variable_name_by_id.get(predicate.variable_id)
            if variable_name is None:
                continue
            variable_ref = _sanitize_identifier(variable_name)
            op = _operator_symbol(predicate.operator)
            value = _predicate_value_literal(predicate)
            bits.append(f'({variable_ref} {op} {value})')
        if not bits:
            continue
        joiner = ' and ' if chain.combinator.value == 'all' else ' or '
        group_exprs.append(f'({joiner.join(bits)})')

    if not group_exprs:
        return None
    return f'({" and ".join(group_exprs)})'


def _effect_lines(
    effect,
    step_index: int,
    outcome_var_names: dict[str, str],
    outcome_name_by_id: dict[int, str],
    session: Session,
) -> list[str]:
    target_name = outcome_name_by_id.get(int(effect.target_outcome_id), f'outcome-{effect.target_outcome_id}')
    target_var = outcome_var_names.get(target_name)
    if target_var is None:
        return []

    if effect.adapter_type == AdapterType.binary:
        return _binary_effect_lines(effect, step_index, target_var, outcome_var_names)
    return _linear_effect_lines(effect, step_index, target_var, outcome_var_names, session)


def _binary_effect_lines(effect, step_index: int, target_var: str, outcome_var_names: dict[str, str]) -> list[str]:
    if effect.likelihood_mode == AdapterLikelihoodMode.set:
        value = _fmt(effect.set_likelihood or 0.0)
        return [f'set {target_var} {value}']
    if effect.likelihood_mode == AdapterLikelihoodMode.add_points:
        value = _fmt(effect.add_points or 0.0)
        return [f'set {target_var} ({target_var} + {value})']
    if effect.likelihood_mode == AdapterLikelihoodMode.probability_multiply:
        factor_expr = _fmt(effect.multiplier or 0.0)
        return _probability_multiply_lines(step_index, target_var, factor_expr, outcome_var_names)
    value = _fmt(effect.multiplier or 1.0)
    return [f'set {target_var} ({target_var} * {value})']


def _linear_effect_lines(effect, step_index: int, target_var: str, outcome_var_names: dict[str, str], session: Session) -> list[str]:
    coeffs = decision_repo.list_coefficients(session, int(effect.id))
    variables = decision_repo.list_variables(session)
    variable_name_by_id = {int(variable.id): variable.name for variable in variables if variable.id is not None}

    terms = [_fmt(effect.intercept or 0.0)]
    for coefficient in coeffs:
        variable_name = variable_name_by_id.get(coefficient.variable_id, f'var-{coefficient.variable_id}')
        terms.append(f'({_fmt(coefficient.coefficient)} * {_sanitize_identifier(variable_name)})')
    raw_expr = ' + '.join(terms)
    tmp_var = f'__lin_{step_index}'
    lines = [f'let {tmp_var} ({raw_expr})']

    min_val = effect.min_multiplier if effect.min_multiplier is not None else 0.0
    lines.append(f'set {tmp_var} (max list {_fmt(min_val)} {tmp_var})')
    if effect.max_multiplier is not None:
        lines.append(f'set {tmp_var} (min list {_fmt(effect.max_multiplier)} {tmp_var})')

    if effect.likelihood_mode == AdapterLikelihoodMode.set:
        lines.append(f'set {target_var} {tmp_var}')
        return lines
    if effect.likelihood_mode == AdapterLikelihoodMode.add_points:
        lines.append(f'set {target_var} ({target_var} + {tmp_var})')
        return lines
    if effect.likelihood_mode == AdapterLikelihoodMode.probability_multiply:
        return lines + _probability_multiply_lines(step_index, target_var, tmp_var, outcome_var_names)
    lines.append(f'set {target_var} ({target_var} * {tmp_var})')
    return lines


def _probability_multiply_lines(
    step_index: int,
    target_var: str,
    factor_expr: str,
    outcome_var_names: dict[str, str],
) -> list[str]:
    all_vars = list(outcome_var_names.values())
    n = len(all_vars)
    total_expr = ' + '.join(f'(max list 0 {var})' for var in all_vars)
    total_var = f'__pm_total_{step_index}'
    factor_var = f'__pm_factor_{step_index}'
    target_prob_var = f'__pm_target_p_{step_index}'
    new_target_prob_var = f'__pm_new_target_p_{step_index}'
    remaining_old_var = f'__pm_remaining_old_{step_index}'
    remaining_new_var = f'__pm_remaining_new_{step_index}'

    lines: list[str] = []
    lines.append(f'let {factor_var} ({factor_expr})')
    lines.append(f'if {factor_var} < 0 [ set {factor_var} 0 ]')
    lines.append(f'let {total_var} ({total_expr})')
    for index, var in enumerate(all_vars):
        old_prob_var = f'__pm_old_{step_index}_{index}'
        lines.append(
            f'let {old_prob_var} (ifelse-value ({total_var} = 0) [{_fmt(1.0 / n)}] [((max list 0 {var}) / {total_var})])'
        )
    target_old_prob_var = f'__pm_old_{step_index}_{all_vars.index(target_var)}'
    lines.append(f'let {target_prob_var} {target_old_prob_var}')
    lines.append(f'let {new_target_prob_var} ({target_prob_var} * {factor_var})')
    lines.append(f'if {new_target_prob_var} < 0 [ set {new_target_prob_var} 0 ]')
    lines.append(f'if {new_target_prob_var} > 1 [ set {new_target_prob_var} 1 ]')
    lines.append(f'let {remaining_old_var} (1 - {target_prob_var})')
    lines.append(f'let {remaining_new_var} (1 - {new_target_prob_var})')
    lines.append(f'ifelse {remaining_old_var} = 0 [')
    for var in all_vars:
        if var == target_var:
            lines.append(f'  set {var} 1')
        else:
            lines.append(f'  set {var} 0')
    lines.append('] [')
    lines.append(f'  set {target_var} {new_target_prob_var}')
    for index, var in enumerate(all_vars):
        if var == target_var:
            continue
        old_prob_var = f'__pm_old_{step_index}_{index}'
        lines.append(f'  set {var} (({old_prob_var} / {remaining_old_var}) * {remaining_new_var})')
    lines.append(']')
    return lines



def _outcome_var_names(names: list[str]) -> dict[str, str]:
    assigned: set[str] = set()
    out: dict[str, str] = {}
    for name in names:
        base = f'likelihood-{_sanitize_identifier(name)}'
        candidate = base
        suffix = 1
        while candidate in assigned:
            suffix += 1
            candidate = f'{base}-{suffix}'
        assigned.add(candidate)
        out[name] = candidate
    return out


def _predicate_value_literal(predicate) -> str:
    if predicate.value_int is not None:
        return str(predicate.value_int)
    if predicate.value_float is not None:
        return _fmt(predicate.value_float)
    if predicate.value_bool is not None:
        return 'true' if predicate.value_bool else 'false'
    return '0'


def _operator_symbol(operator: ConditionOperator) -> str:
    if operator == ConditionOperator.eq:
        return '='
    if operator == ConditionOperator.ne:
        return '!='
    if operator == ConditionOperator.gt:
        return '>'
    if operator == ConditionOperator.gte:
        return '>='
    if operator == ConditionOperator.lt:
        return '<'
    return '<='


def _sanitize_identifier(text: str) -> str:
    cleaned = re.sub(r'[^A-Za-z0-9_-]+', '-', text.strip().lower())
    cleaned = re.sub(r'-{2,}', '-', cleaned).strip('-')
    if not cleaned:
        cleaned = 'reporter'
    if cleaned[0].isdigit():
        cleaned = f'r-{cleaned}'
    return cleaned


def _fmt(value: float) -> str:
    return f'{float(value):.12g}'


def _quote(text: str) -> str:
    return '"' + text.replace('"', '\\"') + '"'
