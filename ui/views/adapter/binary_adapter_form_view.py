from __future__ import annotations

from collections.abc import Callable

from nicegui import ui

from ui.components.form_actions import form_actions


def render_binary_adapter_form(
    *,
    title: str,
    outcome_options: dict[int, str],
    initial_target_outcome_id: int | None,
    initial_multiplier: float,
    on_submit: Callable[[int | None, float], None],
    on_cancel: Callable[[], None],
) -> None:
    ui.label(title).classes('text-h6')
    target_select = ui.select(
        options=outcome_options,
        value=initial_target_outcome_id,
        label='Target outcome',
    ).classes('w-full')
    multiplier_input = ui.number('Multiplier (> 0)', value=initial_multiplier, min=0.0001, step=0.1).classes('w-full')

    def handle_submit() -> None:
        selected = None if target_select.value is None else int(target_select.value)
        on_submit(selected, float(multiplier_input.value or 1.0))

    form_actions(on_save=handle_submit, on_cancel=on_cancel)
