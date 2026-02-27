from __future__ import annotations

from collections.abc import Callable

from nicegui import ui

from models import ConditionOperator
from ui.components.form_actions import form_actions


def render_condition_form(
    *,
    title: str,
    variable_options: dict[int, str],
    initial_variable_id: int | None,
    initial_operator: ConditionOperator | None,
    initial_value: str,
    on_submit: Callable[[int | None, ConditionOperator | None, str], None],
    on_cancel: Callable[[], None],
) -> None:
    ui.label(title).classes('text-h6')

    variable_select = ui.select(
        options=variable_options,
        value=initial_variable_id,
        label='Variable',
    ).classes('w-full')

    operator_select = ui.select(
        options={op.value: op.value for op in ConditionOperator},
        value=None if initial_operator is None else initial_operator.value,
        label='Operator',
    ).classes('w-full')

    value_input = ui.input('Condition value', value=initial_value).classes('w-full')

    def handle_submit() -> None:
        selected_variable = None if variable_select.value is None else int(variable_select.value)
        selected_operator = (
            None if operator_select.value is None else ConditionOperator(str(operator_select.value))
        )
        on_submit(selected_variable, selected_operator, (value_input.value or '').strip())

    form_actions(on_save=handle_submit, on_cancel=on_cancel)
