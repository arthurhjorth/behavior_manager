from __future__ import annotations

from nicegui import ui
from sqlmodel import Session

from models import (
    AdapterType,
    AdapterLikelihoodMode,
    Agent,
    BinaryAdapter,
    LinearAdapter,
    Outcome,
    VarTable,
    VarType,
    VariableRecord,
)
from repositories import decision_repo
from services import decision_service
from ui.components.messages import show_errors


def render_decision_test_view(*, engine, decision_id: int, back_url: str) -> None:
    with Session(engine) as session:
        decision = decision_repo.get_decision(session, decision_id)
        if decision is None:
            ui.label('Decision not found.')
            ui.button('Back', on_click=lambda: ui.navigate.to(back_url))
            return
        used_variables = _used_variables_for_decision(session, decision_id)
        adapter_meta = _adapter_effect_meta(session, decision_id)

    ui.label(f'Test: {decision.name}').classes('text-h6')
    if not used_variables:
        ui.label('No variables are referenced by this decision.').classes('text-body2 text-grey-7')

    variable_inputs: dict[str, tuple[VarType, object]] = {}
    with ui.column().classes('w-full gap-2'):
        for variable in used_variables:
            if variable.var_type == VarType._bool:
                control = ui.switch(variable.name, value=_variable_default(variable)).classes('w-full')
            elif variable.var_type == VarType._int:
                control = ui.number(variable.name, value=_variable_default(variable), step=1, precision=0).classes('w-full')
            else:
                control = ui.number(variable.name, value=_variable_default(variable), step=0.01).classes('w-full')
            variable_inputs[variable.name] = (variable.var_type, control)

    ui.separator()
    ui.label('Adapter activation').classes('text-subtitle2')
    include_state: dict[int, bool] = {}
    for item in adapter_meta:
        include_state[item['id']] = True
    if not adapter_meta:
        ui.label('No adapters configured.').classes('text-body2 text-grey-7')
    else:
        with ui.column().classes('w-full gap-1'):
            for item in adapter_meta:
                checkbox = ui.checkbox(item['label'], value=True).classes('w-full')
                checkbox.on('update:model-value', lambda event, aid=item['id']: include_state.__setitem__(aid, bool(event.value)))

    show_inactive_switch = ui.switch('Show inactive adapters in trace', value=False)
    show_skipped_switch = ui.switch('Show skipped adapters in trace', value=False)

    def run_test() -> None:
        try:
            variable_values = _read_variable_values(variable_inputs)
        except ValueError as exc:
            show_errors([str(exc)])
            return

        try:
            with Session(engine) as session:
                runtime = decision_service.build_runtime_decision(session, decision_id)
            table = VarTable()
            for name, (var_type, value) in variable_values.items():
                table.add(name, var_type, value)
            current = _copy_outcomes(runtime.outcomes or [])
            steps: list[dict] = []
            for index, adapter in enumerate(runtime.adapters, start=1):
                effect_id = adapter_meta[index - 1]['id'] if index - 1 < len(adapter_meta) else index
                step_label = adapter_meta[index - 1]['label'] if index - 1 < len(adapter_meta) else _adapter_label(adapter)
                is_active = include_state.get(effect_id, True)
                before = _copy_outcomes(current)
                applied = _adapter_applies(adapter, table) if is_active else False
                after = _copy_outcomes(adapter.modify(before, table)) if is_active else _copy_outcomes(before)
                steps.append(
                    {
                        'index': index,
                        'effect_id': effect_id,
                        'label': step_label,
                        'active': is_active,
                        'applied': applied,
                        'before': before,
                        'after': after,
                    }
                )
                current = after
            final_raw = _copy_outcomes(current)
            final_probs = _probabilities(final_raw)
        except Exception as exc:
            show_errors([f'Could not run decision: {exc}'])
            return

        results_container.clear()
        with results_container:
            ui.label('Final Results').classes('text-h6')
            for outcome in final_raw:
                probability = max(0.0, final_probs.get(outcome.name, 0.0))
                percent = probability * 100.0
                odds = _weight_value(float(outcome.likelihood))
                with ui.row().classes('w-full items-center justify-between border rounded p-2'):
                    ui.label(outcome.name).classes('text-body1')
                    ui.label(f'Odds: {odds} | Probability: {percent:.2f}%').classes('text-body2 text-grey-8')

            ui.separator()
            ui.label('Execution Trace').classes('text-h6')

            baseline_probs = _probabilities(runtime.outcomes or [])
            with ui.column().classes('w-full border rounded p-2 gap-1'):
                ui.label('Step 0: Baseline').classes('text-body1 text-weight-medium')
                _render_outcome_changes(runtime.outcomes or [], runtime.outcomes or [], baseline_probs, baseline_probs)

            for step in steps:
                if not show_inactive_switch.value and not step['active']:
                    continue
                if not show_skipped_switch.value and step['active'] and not step['applied']:
                    continue
                before_probs = _probabilities(step['before'])
                after_probs = _probabilities(step['after'])
                with ui.column().classes('w-full border rounded p-2 gap-1'):
                    if not step['active']:
                        status = 'inactive'
                        status_color = 'text-grey-7'
                    else:
                        status = 'applied' if step['applied'] else 'skipped'
                        status_color = 'text-positive' if step['applied'] else 'text-grey-7'
                    ui.label(f"Step {step['index']}: {step['label']}").classes('text-body1 text-weight-medium')
                    ui.label(status).classes(f'text-caption {status_color}')
                    _render_outcome_changes(step['before'], step['after'], before_probs, after_probs)

    with ui.row().classes('gap-2'):
        ui.button('Run Test', on_click=run_test, color='primary')
        ui.button('Back', on_click=lambda: ui.navigate.to(back_url))

    results_container = ui.column().classes('w-full gap-2')

    run_test()


def _used_variables_for_decision(session: Session, decision_id: int) -> list[VariableRecord]:
    all_variables = decision_repo.list_variables(session)
    by_id = {int(variable.id): variable for variable in all_variables if variable.id is not None}

    used_variable_ids: set[int] = set()
    for adapter_set in decision_repo.list_adapter_sets(session, decision_id):
        set_id = int(adapter_set.id)
        for effect in decision_repo.list_adapters(session, adapter_set_id=set_id):
            for coefficient in decision_repo.list_coefficients(session, int(effect.id)):
                used_variable_ids.add(int(coefficient.variable_id))
        for chain in decision_repo.list_chains(session, set_id):
            for predicate in decision_repo.list_predicates(session, int(chain.id)):
                used_variable_ids.add(int(predicate.variable_id))

    return [by_id[var_id] for var_id in sorted(used_variable_ids) if var_id in by_id]


def _variable_default(variable: VariableRecord):
    if variable.var_type == VarType._bool:
        return bool(variable.value_bool) if variable.value_bool is not None else False
    if variable.var_type == VarType._int:
        return int(variable.value_int) if variable.value_int is not None else 0
    return float(variable.value_float) if variable.value_float is not None else 0.0


def _read_variable_values(variable_inputs: dict[str, tuple[VarType, object]]) -> dict[str, tuple[VarType, object]]:
    values: dict[str, tuple[VarType, object]] = {}
    for name, (var_type, control) in variable_inputs.items():
        raw = getattr(control, 'value', None)
        if var_type == VarType._bool:
            values[name] = (var_type, bool(raw))
            continue
        if raw is None or str(raw).strip() == '':
            raise ValueError(f'Value is required for {name}.')
        if var_type == VarType._int:
            values[name] = (var_type, int(float(raw)))
            continue
        values[name] = (var_type, float(raw))
    return values


def _weight_value(weight: float) -> str:
    return f'{weight:.3f}'


def _copy_outcomes(outcomes: list[Outcome]) -> list[Outcome]:
    return [Outcome(name=outcome.name, likelihood=float(outcome.likelihood)) for outcome in outcomes]


def _probabilities(outcomes: list[Outcome]) -> dict[str, float]:
    if not outcomes:
        return {}
    clipped = {outcome.name: max(0.0, float(outcome.likelihood)) for outcome in outcomes}
    total = sum(clipped.values())
    if total == 0.0:
        uniform = 1.0 / len(outcomes)
        return {outcome.name: uniform for outcome in outcomes}
    return {name: value / total for name, value in clipped.items()}


def _adapter_applies(adapter, table: VarTable) -> bool:
    try:
        return all(fn(table) for fn in adapter.funcs) if adapter.funcs else True
    except Exception:
        return False


def _adapter_label(adapter) -> str:
    if isinstance(adapter, BinaryAdapter):
        if adapter.likelihood_mode == AdapterLikelihoodMode.set:
            value = '<unset>' if adapter.set_likelihood is None else str(adapter.set_likelihood)
            return f'set {adapter.target_outcome} {value}'
        if adapter.likelihood_mode == AdapterLikelihoodMode.add_points:
            value = '<unset>' if adapter.add_points is None else str(adapter.add_points)
            return f'add {adapter.target_outcome} by {value} %-pts'
        if adapter.likelihood_mode == AdapterLikelihoodMode.probability_multiply:
            return f'multiply probability of {adapter.target_outcome} by {adapter.multiplier}'
        return f'multiply {adapter.target_outcome} by {adapter.multiplier}'

    if isinstance(adapter, LinearAdapter):
        formula = (
            f'linear(intercept={adapter.intercept}, '
            f'min={adapter.min_multiplier}, '
            f'max={adapter.max_multiplier if adapter.max_multiplier is not None else "none"})'
        )
        if adapter.likelihood_mode == AdapterLikelihoodMode.set:
            return f'set {adapter.target_outcome} {formula}'
        if adapter.likelihood_mode == AdapterLikelihoodMode.add_points:
            return f'add {adapter.target_outcome} by {formula} %-pts'
        if adapter.likelihood_mode == AdapterLikelihoodMode.probability_multiply:
            return f'multiply probability of {adapter.target_outcome} by {formula}'
        return f'multiply {adapter.target_outcome} by {formula}'

    return 'adapter'


def _adapter_effect_meta(session: Session, decision_id: int) -> list[dict[str, object]]:
    outcomes = decision_repo.list_outcomes(session, decision_id)
    outcome_name_by_id = {int(outcome.id): outcome.name for outcome in outcomes if outcome.id is not None}
    items: list[dict[str, object]] = []
    for adapter_set in decision_repo.list_adapter_sets(session, decision_id):
        set_name = adapter_set.name
        effects = decision_repo.list_adapters(session, adapter_set_id=int(adapter_set.id))
        for effect in effects:
            effect_id = int(effect.id)
            target = outcome_name_by_id.get(effect.target_outcome_id, f'#{effect.target_outcome_id}')
            label = _effect_row_label(effect, target, set_name)
            items.append({'id': effect_id, 'label': label})
    return items


def _effect_row_label(effect, target: str, set_name: str) -> str:
    prefix = f'[{set_name}] '
    if effect.adapter_type == AdapterType.binary:
        if effect.likelihood_mode == AdapterLikelihoodMode.set:
            value = effect.set_likelihood if effect.set_likelihood is not None else '<unset>'
            return f'{prefix}set {target} {value}'
        if effect.likelihood_mode == AdapterLikelihoodMode.add_points:
            value = effect.add_points if effect.add_points is not None else '<unset>'
            return f'{prefix}add {target} by {value} %-pts'
        if effect.likelihood_mode == AdapterLikelihoodMode.probability_multiply:
            value = effect.multiplier if effect.multiplier is not None else '<unset>'
            return f'{prefix}multiply probability of {target} by {value}'
        value = effect.multiplier if effect.multiplier is not None else '<unset>'
        return f'{prefix}multiply {target} by {value}'

    formula = _linear_summary(effect)
    if effect.likelihood_mode == AdapterLikelihoodMode.set:
        return f'{prefix}set {target} {formula}'
    if effect.likelihood_mode == AdapterLikelihoodMode.add_points:
        return f'{prefix}add {target} by {formula} %-pts'
    if effect.likelihood_mode == AdapterLikelihoodMode.probability_multiply:
        return f'{prefix}multiply probability of {target} by {formula}'
    return f'{prefix}multiply {target} by {formula}'


def _linear_summary(effect) -> str:
    intercept = effect.intercept if effect.intercept is not None else 0.0
    minimum = effect.min_multiplier if effect.min_multiplier is not None else 0.0
    maximum = 'none' if effect.max_multiplier is None else str(effect.max_multiplier)
    return f'linear(intercept={intercept}, min={minimum}, max={maximum})'


def _render_outcome_changes(
    before: list[Outcome],
    after: list[Outcome],
    before_probs: dict[str, float],
    after_probs: dict[str, float],
) -> None:
    after_by_name = {outcome.name: outcome for outcome in after}
    for before_outcome in before:
        after_outcome = after_by_name.get(before_outcome.name, before_outcome)
        before_weight = float(before_outcome.likelihood)
        after_weight = float(after_outcome.likelihood)
        before_percent = before_probs.get(before_outcome.name, 0.0) * 100.0
        after_percent = after_probs.get(before_outcome.name, 0.0) * 100.0
        delta = after_percent - before_percent
        delta_prefix = '+' if delta >= 0 else ''
        with ui.row().classes('w-full items-center justify-between'):
            ui.label(before_outcome.name).classes('text-body2')
            ui.label(
                f'{before_weight:.3f} ({before_percent:.2f}%) -> '
                f'{after_weight:.3f} ({after_percent:.2f}%) '
                f'[{delta_prefix}{delta:.2f} pts]'
            ).classes('text-caption text-grey-8')
