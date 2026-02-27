from __future__ import annotations

from collections.abc import Callable

from nicegui import ui
from sqlmodel import Session

from models import OutcomeRecord
from repositories import decision_repo
from ui.components.confirm_actions import confirm_delete_button


def render_outcome_list(
    *,
    engine,
    decision_id: int,
    on_edit: Callable[[int], None],
    on_create: Callable[[], None],
    on_delete: Callable[[int], None],
) -> None:
    ui.label('Outcomes').classes('text-h6')

    with Session(engine) as session:
        outcomes = decision_repo.list_outcomes(session, decision_id)

    if not outcomes:
        ui.label('No outcomes yet.')
    else:
        for outcome in outcomes:
            _render_outcome_row(outcome, on_edit, on_delete)

    ui.button('Add Outcome', on_click=lambda: on_create(), color='primary').props('outline')


def _render_outcome_row(
    outcome: OutcomeRecord,
    on_edit: Callable[[int], None],
    on_delete: Callable[[int], None],
) -> None:
    likelihood_label = '<unset>' if outcome.likelihood is None else f'{outcome.likelihood:.3f}'
    with ui.row().classes('items-center justify-between w-full border rounded p-2'):
        ui.label(f'{outcome.name}: {likelihood_label}')
        with ui.row().classes('gap-1'):
            ui.button('Edit', on_click=lambda oid=outcome.id: on_edit(int(oid))).props('flat')
            confirm_delete_button(
                label='Delete',
                item_name=f'outcome "{outcome.name}"',
                on_confirm=lambda oid=outcome.id: on_delete(int(oid)),
            )
