from __future__ import annotations

from collections.abc import Callable

from nicegui import ui

from ui.components.form_actions import form_actions


def render_coefficient_edit_view(
    *,
    title: str,
    variable_options: dict[int, str],
    initial_variable_id: int | None,
    initial_coefficient: float,
    on_submit: Callable[[int | None, float], None],
    on_cancel: Callable[[], None],
) -> None:
    ui.label(title).classes('text-h6')
    variable_select = ui.select(
        options=variable_options,
        value=initial_variable_id,
        label='Variable',
    ).classes('w-full')
    coefficient_input = ui.number('Coefficient', value=initial_coefficient, step=0.1).classes('w-full')

    def handle_submit() -> None:
        selected = None if variable_select.value is None else int(variable_select.value)
        on_submit(selected, float(coefficient_input.value or 0.0))

    form_actions(on_save=handle_submit, on_cancel=on_cancel)
