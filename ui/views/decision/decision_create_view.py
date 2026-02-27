from __future__ import annotations

from nicegui import ui
from sqlmodel import Session

from repositories import decision_repo
from services import decision_service
from ui.components.messages import show_errors
from ui.views.decision.decision_form_view import render_decision_form


def render_decision_create_view(*, engine, back_url: str, after_create_base_url: str) -> None:
    def handle_submit(name: str, description: str) -> None:
        errors = decision_service.validate_decision_payload(name, description)
        if errors:
            show_errors(err.message for err in errors)
            return

        with Session(engine) as session:
            record = decision_repo.create_decision(
                session,
                name=name,
                description=description,
            )
        ui.navigate.to(f'{after_create_base_url}/{record.id}')

    render_decision_form(
        title='Create Decision',
        initial_name='',
        initial_description='',
        on_submit=handle_submit,
        on_cancel=lambda: ui.navigate.to(back_url),
    )
