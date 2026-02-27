from __future__ import annotations

from collections.abc import Callable

from nicegui import ui

from ui.components.form_actions import form_actions


def render_decision_form(
    *,
    title: str,
    initial_name: str,
    initial_description: str,
    on_submit: Callable[[str, str], None],
    on_cancel: Callable[[], None],
) -> None:
    ui.label(title).classes('text-h6')
    name_input = ui.input('Decision name', value=initial_name).classes('w-full')
    description_input = ui.textarea('Description', value=initial_description).classes('w-full')

    def handle_submit() -> None:
        on_submit((name_input.value or '').strip(), (description_input.value or '').strip())

    form_actions(on_save=handle_submit, on_cancel=on_cancel)
