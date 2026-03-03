from __future__ import annotations

from collections.abc import Callable

from nicegui import ui
from sqlmodel import Session

from models import AdapterLikelihoodMode, AdapterType
from repositories import decision_repo
from ui.components.confirm_actions import confirm_delete_button


def render_adapter_list(
    *,
    engine,
    decision_id: int,
    on_edit: Callable[[int], None],
    on_create: Callable[[], None],
    on_delete: Callable[[int], None],
) -> None:
    ui.label('Adapter Sets').classes('text-h6')

    with Session(engine) as session:
        sets = decision_repo.list_adapter_sets(session, decision_id)
        outcomes = decision_repo.list_outcomes(session, decision_id)
        variables = decision_repo.list_variables(session)
        outcome_names = {int(outcome.id): outcome.name for outcome in outcomes if outcome.id is not None}
        variable_names = {int(variable.id): variable.name for variable in variables if variable.id is not None}

    if not sets:
        ui.label('No adapter sets yet.')
    else:
        for adapter_set in sets:
            with Session(engine) as session:
                chains = decision_repo.list_chains(session, int(adapter_set.id))
                effects = decision_repo.list_adapters(session, adapter_set_id=int(adapter_set.id))
                chain_text = _set_condition_text(session, chains, variable_names)
                effect_text = _set_effect_text(effects, outcome_names)
            with ui.row().classes('items-center justify-between w-full border rounded p-2'):
                ui.label(f'{chain_text} then {effect_text}')
                with ui.row().classes('gap-1'):
                    ui.button('Edit', on_click=lambda sid=adapter_set.id: on_edit(int(sid))).props('flat')
                    confirm_delete_button(
                        label='Delete',
                        item_name=f'adapter set \"{adapter_set.name}\"',
                        on_confirm=lambda sid=adapter_set.id: on_delete(int(sid)),
                    )

    ui.button('Add Adapter Set', on_click=lambda: on_create(), color='primary').props('outline')


def _set_condition_text(session: Session, chains, variable_names: dict[int, str]) -> str:
    if not chains:
        return 'if always'

    parts = []
    for chain in chains:
        predicates = decision_repo.list_predicates(session, int(chain.id))
        if not predicates:
            continue
        predicate_bits = []
        for predicate in predicates:
            var_name = variable_names.get(predicate.variable_id, f'#{predicate.variable_id}')
            predicate_bits.append(f'{var_name} {predicate.operator.value} {_predicate_value(predicate)}')
        joiner = ' AND ' if chain.combinator.value == 'all' else ' OR '
        parts.append(f'({joiner.join(predicate_bits)})')

    if not parts:
        return 'if always'
    return f'if {" AND ".join(parts)}'


def _set_effect_text(effects, outcome_names: dict[int, str]) -> str:
    if not effects:
        return 'do nothing'

    bits = []
    for effect in effects:
        target = outcome_names.get(effect.target_outcome_id, f'#{effect.target_outcome_id}')
        if effect.adapter_type == AdapterType.binary:
            if effect.likelihood_mode == AdapterLikelihoodMode.set:
                value = effect.set_likelihood if effect.set_likelihood is not None else '<unset>'
                bits.append(f'set {target} {value}')
            elif effect.likelihood_mode == AdapterLikelihoodMode.add_points:
                value = effect.add_points if effect.add_points is not None else '<unset>'
                bits.append(f'add {target} by {value} %-pts')
            elif effect.likelihood_mode == AdapterLikelihoodMode.probability_multiply:
                value = effect.multiplier if effect.multiplier is not None else '<unset>'
                bits.append(f'multiply probability of {target} by {value}')
            else:
                value = effect.multiplier if effect.multiplier is not None else '<unset>'
                bits.append(f'multiply {target} by {value}')
            continue

        if effect.likelihood_mode == AdapterLikelihoodMode.set:
            bits.append(f'set {target} {_linear_summary(effect)}')
        elif effect.likelihood_mode == AdapterLikelihoodMode.add_points:
            bits.append(f'add {target} by {_linear_summary(effect)} %-pts')
        elif effect.likelihood_mode == AdapterLikelihoodMode.probability_multiply:
            bits.append(f'multiply probability of {target} by {_linear_summary(effect)}')
        else:
            bits.append(f'multiply {target} by {_linear_summary(effect)}')
    return '; '.join(bits)


def _linear_summary(effect) -> str:
    intercept = effect.intercept if effect.intercept is not None else 0.0
    minimum = effect.min_multiplier if effect.min_multiplier is not None else 0.0
    maximum = 'none' if effect.max_multiplier is None else str(effect.max_multiplier)
    return f'linear(intercept={intercept}, min={minimum}, max={maximum})'


def _predicate_value(predicate) -> str:
    if predicate.value_int is not None:
        return str(predicate.value_int)
    if predicate.value_float is not None:
        return str(predicate.value_float)
    if predicate.value_bool is not None:
        return 'true' if predicate.value_bool else 'false'
    return '<unset>'
