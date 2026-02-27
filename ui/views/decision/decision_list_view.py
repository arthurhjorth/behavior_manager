from __future__ import annotations

from collections.abc import Callable

from nicegui import ui
from sqlmodel import Session

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
            with ui.row().classes('items-center justify-between w-full border rounded p-2'):
                ui.label(f'{decision.name} - {decision.description}')
                with ui.row().classes('gap-1'):
                    ui.button('Open', on_click=lambda did=decision.id: on_select(int(did)), color='primary').props('flat')
                    confirm_delete_button(
                        label='Delete',
                        item_name=f'decision "{decision.name}"',
                        on_confirm=lambda did=decision.id: on_delete(int(did)),
                    )

    ui.button('Create Decision', on_click=lambda: on_create(), color='primary')
