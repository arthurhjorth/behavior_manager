from __future__ import annotations

from nicegui import ui
from sqlmodel import Session

from repositories import decision_repo
from services import decision_service
from ui.components.messages import show_errors
from ui.views.outcome.outcome_form_view import render_outcome_form


def render_outcome_create_view(*, engine, decision_id: int, back_url: str) -> None:
    def handle_submit(name: str, likelihood: float | None) -> None:
        errors = decision_service.validate_outcome_payload(name, likelihood)
        if errors:
            show_errors(err.message for err in errors)
            return
        with Session(engine) as session:
            decision_repo.create_outcome(session, decision_id=decision_id, name=name, likelihood=likelihood)
        ui.navigate.to(back_url)

    render_outcome_form(
        title='Create Outcome',
        initial_name='',
        initial_likelihood=None,
        on_submit=handle_submit,
        on_cancel=lambda: ui.navigate.to(back_url),
    )
