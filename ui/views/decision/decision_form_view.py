from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from nicegui import ui

from ui.components.form_actions import form_actions


@dataclass
class ContextOption:
    id: int
    name: str


def render_decision_form(
    *,
    title: str,
    initial_name: str,
    initial_description: str,
    context_options: list[ContextOption],
    initial_context_ids: list[int],
    on_submit: Callable[[str, str, list[int]], None],
    on_cancel: Callable[[], None],
) -> None:
    ui.label(title).classes('text-h6')
    name_input = ui.input('Decision name', value=initial_name).classes('w-full')
    description_input = ui.textarea('Description', value=initial_description).classes('w-full')
    ui.label('Contexts').classes('text-caption text-grey-7')

    selected_context_ids: set[int] = set(initial_context_ids)
    if not context_options:
        ui.label('No contexts defined. Empty selection means all contexts.').classes('text-body2 text-grey-7')
    else:
        with ui.column().classes('w-full gap-1'):
            for context in context_options:
                checkbox = ui.checkbox(context.name, value=context.id in selected_context_ids)

                def handle_change(event, context_id=context.id) -> None:
                    if bool(event.value):
                        selected_context_ids.add(context_id)
                    else:
                        selected_context_ids.discard(context_id)

                checkbox.on('update:model-value', handle_change)
        ui.label('If none are checked, this decision applies to all contexts.').classes('text-caption text-grey-7')

    def handle_submit() -> None:
        on_submit(
            (name_input.value or '').strip(),
            (description_input.value or '').strip(),
            sorted(selected_context_ids),
        )

    form_actions(on_save=handle_submit, on_cancel=on_cancel)
