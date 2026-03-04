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
    outcome_name_by_id = {int(outcome.id): outcome.name for outcome in outcomes if outcome.id is not None}

    reporter_name = _sanitize_identifier(decision.name)
    lines: list[str] = []
    lines.extend(_netlogo_helper_library_lines())
    lines.append('')
    lines.append(f'to-report {reporter_name}')
    initial_rows = ' '.join(
        f'(list {_quote(outcome.name)} {_fmt(float(outcome.likelihood) if outcome.likelihood is not None else 0.0)})'
        for outcome in outcomes
    )
    lines.append(f'  let __outcomes (list {initial_rows})')

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
                lines.extend(_effect_lines(effect, step_index, outcome_name_by_id, session))
            continue

        lines.append(f'  if {condition_expr} [')
        for effect in effects:
            step_index += 1
            for effect_line in _effect_lines(effect, step_index, outcome_name_by_id, session):
                lines.append(f'    {effect_line}')
        lines.append('  ]')

    lines.append('  report (bm-normalize __outcomes)')
    lines.append('end')
    return '\n'.join(lines)


def _netlogo_helper_library_lines() -> list[str]:
    return [
        'to-report bm-outcome-value [rows target]',
        '  let value 0',
        '  foreach rows [row ->',
        '    if (item 0 row) = target [',
        '      set value (item 1 row)',
        '    ]',
        '  ]',
        '  report value',
        'end',
        '',
        'to-report bm-map-set [rows target new-value]',
        '  report map [row ->',
        '    (ifelse-value ((item 0 row) = target)',
        '      [list (item 0 row) new-value]',
        '      [row])',
        '  ] rows',
        'end',
        '',
        'to-report bm-normalize [rows]',
        '  let clipped map [row -> list (item 0 row) (max list 0 (item 1 row))] rows',
        '  let total sum map [row -> item 1 row] clipped',
        '  ifelse total = 0 [',
        '    let n length clipped',
        '    ifelse n = 0 [',
        '      report []',
        '    ] [',
        '      report map [row -> list (item 0 row) (1 / n)] clipped',
        '    ]',
        '  ] [',
        '    report map [row -> list (item 0 row) ((item 1 row) / total)] clipped',
        '  ]',
        'end',
        '',
        'to-report bm-apply-set [rows target value]',
        '  report bm-map-set rows target value',
        'end',
        '',
        'to-report bm-apply-multiply [rows target factor]',
        '  report bm-map-set rows target ((bm-outcome-value rows target) * factor)',
        'end',
        '',
        'to-report bm-apply-add-points [rows target delta]',
        '  report bm-map-set rows target ((bm-outcome-value rows target) + delta)',
        'end',
        '',
        'to-report bm-apply-probability-multiply [rows target factor]',
        '  if factor < 0 [ set factor 0 ]',
        '  let probs bm-normalize rows',
        '  let target-p bm-outcome-value probs target',
        '  let new-target-p target-p * factor',
        '  if new-target-p < 0 [ set new-target-p 0 ]',
        '  if new-target-p > 1 [ set new-target-p 1 ]',
        '  let remaining-old (1 - target-p)',
        '  let remaining-new (1 - new-target-p)',
        '  ifelse remaining-old = 0 [',
        '    report map [row ->',
        '      (ifelse-value ((item 0 row) = target)',
        '        [list (item 0 row) 1]',
        '        [list (item 0 row) 0])',
        '    ] probs',
        '  ] [',
        '    report map [row ->',
        '      (ifelse-value ((item 0 row) = target)',
        '        [list (item 0 row) new-target-p]',
        '        [list (item 0 row) (((item 1 row) / remaining-old) * remaining-new)])',
        '    ] probs',
        '  ]',
        'end',
    ]


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
            var_ref = _sanitize_identifier(variable_name)
            op = _operator_symbol(predicate.operator)
            value = _predicate_value_literal(predicate)
            bits.append(f'({var_ref} {op} {value})')
        if not bits:
            continue
        joiner = ' and ' if chain.combinator.value == 'all' else ' or '
        group_exprs.append(f'({joiner.join(bits)})')

    if not group_exprs:
        return None
    return f'({" and ".join(group_exprs)})'


def _effect_lines(effect, step_index: int, outcome_name_by_id: dict[int, str], session: Session) -> list[str]:
    target_name = outcome_name_by_id.get(int(effect.target_outcome_id))
    if target_name is None:
        return []
    target_literal = _quote(target_name)

    if effect.adapter_type == AdapterType.binary:
        return _binary_effect_lines(effect, target_literal)
    return _linear_effect_lines(effect, step_index, target_literal, session)


def _binary_effect_lines(effect, target_literal: str) -> list[str]:
    if effect.likelihood_mode == AdapterLikelihoodMode.set:
        value = _fmt(effect.set_likelihood or 0.0)
        return [f'set __outcomes (bm-apply-set __outcomes {target_literal} {value})']
    if effect.likelihood_mode == AdapterLikelihoodMode.add_points:
        value = _fmt(effect.add_points or 0.0)
        return [f'set __outcomes (bm-apply-add-points __outcomes {target_literal} {value})']
    if effect.likelihood_mode == AdapterLikelihoodMode.probability_multiply:
        value = _fmt(effect.multiplier or 0.0)
        return [f'set __outcomes (bm-apply-probability-multiply __outcomes {target_literal} {value})']
    value = _fmt(effect.multiplier or 1.0)
    return [f'set __outcomes (bm-apply-multiply __outcomes {target_literal} {value})']


def _linear_effect_lines(effect, step_index: int, target_literal: str, session: Session) -> list[str]:
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
        lines.append(f'set __outcomes (bm-apply-set __outcomes {target_literal} {tmp_var})')
    elif effect.likelihood_mode == AdapterLikelihoodMode.add_points:
        lines.append(f'set __outcomes (bm-apply-add-points __outcomes {target_literal} {tmp_var})')
    elif effect.likelihood_mode == AdapterLikelihoodMode.probability_multiply:
        lines.append(f'set __outcomes (bm-apply-probability-multiply __outcomes {target_literal} {tmp_var})')
    else:
        lines.append(f'set __outcomes (bm-apply-multiply __outcomes {target_literal} {tmp_var})')
    return lines


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
