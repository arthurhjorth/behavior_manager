from __future__ import annotations

from nicegui import ui
from sqlmodel import Session

from models import Agent, VarTable, VarType, VariableRecord
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

    results_container = ui.column().classes('w-full gap-2')

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
            agent = Agent(my_variables=table)
            raw_outcomes = agent.run_decision_raw(runtime)
            outcomes = agent.run_decision(runtime)
        except Exception as exc:
            show_errors([f'Could not run decision: {exc}'])
            return

        probabilities_by_name = {outcome.name: float(outcome.likelihood) for outcome in outcomes}
        results_container.clear()
        with results_container:
            ui.label('Results').classes('text-h6')
            for outcome in raw_outcomes:
                probability = max(0.0, probabilities_by_name.get(outcome.name, 0.0))
                percent = probability * 100.0
                odds = _odds_value(float(outcome.likelihood))
                with ui.row().classes('w-full items-center justify-between border rounded p-2'):
                    ui.label(outcome.name).classes('text-body1')
                    ui.label(f'Odds: {odds} | Probability: {percent:.2f}%').classes('text-body2 text-grey-8')

    with ui.row().classes('gap-2'):
        ui.button('Run Test', on_click=run_test, color='primary')
        ui.button('Back', on_click=lambda: ui.navigate.to(back_url))

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


def _odds_value(weight: float) -> str:
    return f'{weight:.3f}'
