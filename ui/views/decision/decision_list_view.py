from __future__ import annotations

from collections.abc import Callable
from typing import Any

from nicegui import ui
from sqlmodel import Session

from models import AdapterLikelihoodMode, AdapterType
from repositories import decision_repo
from ui.components.confirm_actions import confirm_delete_button


def render_decision_list(
    *,
    engine,
    on_select: Callable[[int], None],
    on_create: Callable[[], None],
    on_delete: Callable[[int], None],
) -> None:
    ui.label('Decisions').classes('text-h5')

    with Session(engine) as session:
        decisions = decision_repo.list_decisions(session)

    if not decisions:
        ui.label('No decisions yet.')
    else:
        for decision in decisions:
            with Session(engine) as session:
                outcomes = decision_repo.list_outcomes(session, int(decision.id))
                adapter_views = _adapter_views(session, int(decision.id))
                variable_dependencies = _decision_variable_dependencies(session, int(decision.id))

            with ui.column().classes('w-full border rounded p-2 gap-2'):
                with ui.row().classes('items-center justify-between w-full'):
                    ui.label(f'{decision.name} - {decision.description}')
                    with ui.row().classes('gap-1'):
                        ui.button(
                            'Test',
                            on_click=lambda did=decision.id: ui.navigate.to(f'/decisions/{int(did)}/test'),
                            color='primary',
                        ).props('flat')
                        ui.button('Open', on_click=lambda did=decision.id: on_select(int(did)), color='primary').props('flat')
                        confirm_delete_button(
                            label='Delete',
                            item_name=f'decision "{decision.name}"',
                            on_confirm=lambda did=decision.id: on_delete(int(did)),
                        )

                with ui.column().classes('gap-1'):
                    ui.label('Outcomes').classes('text-caption text-grey-7')
                    with ui.row().classes('w-full gap-2 flex-wrap'):
                        if not outcomes:
                            ui.label('None').classes('text-body2')
                        else:
                            for outcome in outcomes:
                                if outcome.likelihood is None:
                                    chip_text = outcome.name
                                else:
                                    chip_text = f'{outcome.name} ({outcome.likelihood:g})'
                                ui.label(chip_text).classes('border rounded px-2 py-1 text-caption')

                with ui.column().classes('gap-1'):
                    ui.label('Variable dependencies').classes('text-caption text-grey-7')
                    if not variable_dependencies:
                        ui.label('None').classes('text-body2')
                    else:
                        with ui.row().classes('w-full gap-2 flex-wrap'):
                            for variable_name in variable_dependencies:
                                ui.label(variable_name).classes('border rounded px-2 py-1 text-caption')

                with ui.column().classes('gap-1'):
                    if not adapter_views:
                        ui.label('No adapter sets')
                    else:
                        for adapter_view in adapter_views:
                            with ui.row().classes('w-full items-center gap-1 flex-wrap'):
                                if not adapter_view['predicate_groups']:
                                    ui.label('if always').classes('text-body2')
                                else:
                                    ui.label('if').classes('text-body2')
                                    for group_index, predicate_group in enumerate(adapter_view['predicate_groups']):
                                        if group_index > 0:
                                            ui.label('AND').classes('text-caption text-grey-7')
                                        ui.label('(').classes('text-grey-7')
                                        for predicate_index, predicate in enumerate(predicate_group['predicates']):
                                            if predicate_index > 0:
                                                ui.label(predicate_group['joiner']).classes('text-caption text-grey-7')
                                            ui.label(predicate['text']).classes(
                                                _predicate_chip_classes(predicate['bool_tone'])
                                            )
                                        ui.label(')').classes('text-grey-7')
                                ui.label('then').classes('text-body2')
                                ui.label(adapter_view['effect_text']).classes('text-body2')

    ui.button('Create Decision', on_click=lambda: on_create(), color='primary')


def _adapter_views(session: Session, decision_id: int) -> list[dict[str, Any]]:
    outcomes = decision_repo.list_outcomes(session, decision_id)
    variables = decision_repo.list_variables(session)
    outcome_names = {int(outcome.id): outcome.name for outcome in outcomes if outcome.id is not None}
    variable_names = {int(variable.id): variable.name for variable in variables if variable.id is not None}

    views: list[dict[str, Any]] = []
    for adapter_set in decision_repo.list_adapter_sets(session, decision_id):
        chains = decision_repo.list_chains(session, int(adapter_set.id))
        effects = decision_repo.list_adapters(session, adapter_set_id=int(adapter_set.id))
        predicate_groups = _predicate_groups_view(session, chains, variable_names)
        effect_text = _set_effect_text(effects, outcome_names)
        views.append({'predicate_groups': predicate_groups, 'effect_text': effect_text})
    return views


def _decision_variable_dependencies(session: Session, decision_id: int) -> list[str]:
    variables = decision_repo.list_variables(session)
    variable_names = {int(variable.id): variable.name for variable in variables if variable.id is not None}
    used_variable_ids: set[int] = set()

    for adapter_set in decision_repo.list_adapter_sets(session, decision_id):
        for chain in decision_repo.list_chains(session, int(adapter_set.id)):
            for predicate in decision_repo.list_predicates(session, int(chain.id)):
                used_variable_ids.add(int(predicate.variable_id))
        for effect in decision_repo.list_adapters(session, adapter_set_id=int(adapter_set.id)):
            for coefficient in decision_repo.list_coefficients(session, int(effect.id)):
                used_variable_ids.add(int(coefficient.variable_id))

    return sorted(variable_names[var_id] for var_id in used_variable_ids if var_id in variable_names)


def _predicate_groups_view(session: Session, chains, variable_names: dict[int, str]) -> list[dict[str, Any]]:
    groups: list[dict[str, Any]] = []
    for chain in chains:
        predicates = decision_repo.list_predicates(session, int(chain.id))
        if not predicates:
            continue
        predicate_bits: list[dict[str, str | None]] = []
        for predicate in predicates:
            var_name = variable_names.get(predicate.variable_id, f'#{predicate.variable_id}')
            value = _predicate_value(predicate)
            bool_tone = _predicate_bool_tone(predicate)
            predicate_bits.append({'text': f'{var_name} {predicate.operator.value} {value}', 'bool_tone': bool_tone})
        joiner = ' AND ' if chain.combinator.value == 'all' else ' OR '
        groups.append({'joiner': joiner.strip(), 'predicates': predicate_bits})
    return groups


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
            else:
                value = effect.multiplier if effect.multiplier is not None else '<unset>'
                bits.append(f'multiply {target} by {value}')
            continue

        if effect.likelihood_mode == AdapterLikelihoodMode.set:
            bits.append(f'set {target} {_linear_summary(effect)}')
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


def _predicate_bool_tone(predicate) -> str | None:
    if predicate.value_bool is None:
        return None
    operator = predicate.operator.value
    value = bool(predicate.value_bool)
    if (operator == 'eq' and value) or (operator == 'ne' and not value):
        return 'true'
    if (operator == 'eq' and not value) or (operator == 'ne' and value):
        return 'false'
    return None


def _predicate_chip_classes(bool_tone: str | None) -> str:
    base = 'border rounded px-2 py-1 text-caption font-mono'
    if bool_tone == 'true':
        return f'{base} bg-green-1 text-green-10 border-green-4'
    if bool_tone == 'false':
        return f'{base} bg-red-1 text-red-10 border-red-4'
    return f'{base} bg-grey-1 text-grey-9 border-grey-4'
