from __future__ import annotations

from nicegui import ui
from sqlmodel import Session

from repositories import decision_repo
from services import decision_service
from ui.components.messages import show_errors
from ui.views.adapter.adapter_list_view import render_adapter_list
from ui.views.decision.decision_form_view import render_decision_form
from ui.views.outcome.outcome_list_view import render_outcome_list
from ui.components.confirm_actions import confirm_delete_button


def render_decision_edit_view(*, engine, decision_id: int, back_url: str) -> None:
    with Session(engine) as session:
        decision = decision_repo.get_decision(session, decision_id)

    if decision is None:
        ui.label('Decision not found.')
        ui.button('Back', on_click=lambda: ui.navigate.to(back_url))
        return

    with ui.column().classes('w-full gap-4'):
        with ui.row().classes('justify-end w-full'):
            confirm_delete_button(
                label='Delete Decision',
                item_name=f'decision "{decision.name}"',
                on_confirm=lambda: _delete_decision(engine, decision_id, back_url),
            )

        render_decision_form(
            title=f'Edit Decision #{decision_id}',
            initial_name=decision.name,
            initial_description=decision.description,
            on_submit=lambda name, description: _update_decision(
                engine,
                decision_id,
                name,
                description,
            ),
            on_cancel=lambda: ui.navigate.to(back_url),
        )

        ui.separator()
        render_outcome_list(
            engine=engine,
            decision_id=decision_id,
            on_edit=lambda outcome_id: ui.navigate.to(f'/decisions/{decision_id}/outcomes/{outcome_id}/edit'),
            on_create=lambda: ui.navigate.to(f'/decisions/{decision_id}/outcomes/new'),
            on_delete=lambda outcome_id: _delete_outcome(engine, decision_id, outcome_id),
        )

        ui.separator()
        render_adapter_list(
            engine=engine,
            decision_id=decision_id,
            on_edit=lambda adapter_id: ui.navigate.to(f'/decisions/{decision_id}/adapters/{adapter_id}/edit'),
            on_create=lambda: ui.navigate.to(f'/decisions/{decision_id}/adapters/new'),
            on_delete=lambda adapter_id: _delete_adapter(engine, decision_id, adapter_id),
        )


def _update_decision(engine, decision_id: int, name: str, description: str) -> None:
    errors = decision_service.validate_decision_payload(name, description)
    if errors:
        show_errors(err.message for err in errors)
        return
    with Session(engine) as session:
        decision_repo.update_decision(session, decision_id, name, description)
    ui.notify('Decision saved.', color='positive')


def _delete_decision(engine, decision_id: int, back_url: str) -> None:
    with Session(engine) as session:
        decision_repo.delete_decision(session, decision_id)
    ui.notify('Decision deleted.', color='positive')
    ui.navigate.to(back_url)


def _delete_outcome(engine, decision_id: int, outcome_id: int) -> None:
    with Session(engine) as session:
        decision_repo.delete_outcome(session, outcome_id)
    ui.notify('Outcome deleted.', color='positive')
    ui.navigate.to(f'/decisions/{decision_id}')


def _delete_adapter(engine, decision_id: int, adapter_id: int) -> None:
    with Session(engine) as session:
        decision_repo.delete_adapter(session, adapter_id)
    ui.notify('Adapter deleted.', color='positive')
    ui.navigate.to(f'/decisions/{decision_id}')
