from __future__ import annotations

from collections.abc import Callable

from nicegui import ui
from sqlmodel import Session

from repositories import decision_repo
from ui.components.confirm_actions import confirm_delete_button


def render_context_list(
    *,
    engine,
    on_create: Callable[[str], None],
    on_delete: Callable[[int], None],
) -> None:
    with Session(engine) as session:
        contexts = decision_repo.list_contexts(session)
        decisions = decision_repo.list_decisions(session)
        linked_names_by_context: dict[int, list[str]] = {}
        for decision in decisions:
            for context in decision.contexts:
                if context.id is None:
                    continue
                linked_names_by_context.setdefault(int(context.id), []).append(decision.name)

    ui.label('Contexts').classes('text-h5')
    with ui.row().classes('w-full items-center gap-2'):
        name_input = ui.input('New context name').classes('w-full')

        def handle_create() -> None:
            name = (name_input.value or '').strip()
            if not name:
                ui.notify('Context name is required.', color='negative')
                return
            on_create(name)

        ui.button('Create Context', on_click=handle_create, color='primary')

    if not contexts:
        ui.label('No contexts yet.')

    for context in contexts:
        decision_names = linked_names_by_context.get(int(context.id), [])
        with ui.column().classes('w-full border rounded p-2 gap-1'):
            with ui.row().classes('items-center justify-between w-full'):
                ui.label(context.name).classes('text-body1')
                confirm_delete_button(
                    label='Delete',
                    item_name=f'context "{context.name}"',
                    on_confirm=lambda cid=context.id: on_delete(int(cid)),
                )
            if not decision_names:
                ui.label('Used by: no decisions').classes('text-caption text-grey-7')
            else:
                with ui.row().classes('w-full gap-2 flex-wrap'):
                    ui.label('Used by:').classes('text-caption text-grey-7')
                    for name in sorted(decision_names):
                        ui.label(name).classes('border rounded px-2 py-1 text-caption')
