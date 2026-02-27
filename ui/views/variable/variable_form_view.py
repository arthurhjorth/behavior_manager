from __future__ import annotations

from collections.abc import Callable

from nicegui import ui

from models import VarType
from ui.components.form_actions import form_actions


def render_variable_form(
    *,
    title: str,
    initial_name: str,
    initial_var_type: VarType,
    initial_value: str,
    initial_is_observer: bool,
    initial_is_turtle: bool,
    initial_is_patch: bool,
    initial_is_link: bool,
    initial_breed: str,
    on_submit: Callable[[str, VarType, str, bool, bool, bool, bool, str], None],
    on_cancel: Callable[[], None],
) -> None:
    ui.label(title).classes('text-h6')

    name_input = ui.input('Name', value=initial_name).classes('w-full')
    type_select = ui.select(
        options={vt.value: vt.value for vt in VarType},
        value=initial_var_type.value,
        label='Type',
    ).classes('w-full')
    value_input = ui.input('Value (optional)', value=initial_value).classes('w-full')

    with ui.row().classes('gap-4 flex-wrap'):
        is_observer = ui.checkbox('Observer', value=initial_is_observer)
        is_turtle = ui.checkbox('Turtle', value=initial_is_turtle)
        is_patch = ui.checkbox('Patch', value=initial_is_patch)
        is_link = ui.checkbox('Link', value=initial_is_link)

    breed_input = ui.input('Breed', value=initial_breed).classes('w-full')

    def handle_submit() -> None:
        selected_type = VarType(type_select.value)
        on_submit(
            (name_input.value or '').strip(),
            selected_type,
            (value_input.value or '').strip(),
            bool(is_observer.value),
            bool(is_turtle.value),
            bool(is_patch.value),
            bool(is_link.value),
            (breed_input.value or '').strip(),
        )

    form_actions(on_save=handle_submit, on_cancel=on_cancel)
