from __future__ import annotations

from nicegui import ui
from sqlmodel import Session

from models import OutcomeRecord
from repositories import decision_repo
from services import decision_service
from ui.components.messages import show_errors
from ui.views.outcome.outcome_form_view import render_outcome_form


def render_outcome_edit_view(*, engine, outcome_id: int, back_url: str) -> None:
    with Session(engine) as session:
        row = session.get(OutcomeRecord, outcome_id)

    if row is None:
        ui.label('Outcome not found.')
        ui.button('Back', on_click=lambda: ui.navigate.to(back_url))
        return

    def handle_submit(name: str, likelihood: float | None) -> None:
        errors = decision_service.validate_outcome_payload(name, likelihood)
        if errors:
            show_errors(err.message for err in errors)
            return
        with Session(engine) as session:
            decision_repo.update_outcome(session, outcome_id=outcome_id, name=name, likelihood=likelihood)
        ui.navigate.to(back_url)

    render_outcome_form(
        title=f'Edit Outcome #{outcome_id}',
        initial_name=row.name,
        initial_likelihood=row.likelihood,
        on_submit=handle_submit,
        on_cancel=lambda: ui.navigate.to(back_url),
    )
