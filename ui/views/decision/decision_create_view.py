from __future__ import annotations

from nicegui import ui
from sqlmodel import Session

from repositories import decision_repo
from services import decision_service
from ui.components.messages import show_errors
from ui.views.decision.decision_form_view import ContextOption, render_decision_form


def render_decision_create_view(*, engine, back_url: str, after_create_base_url: str) -> None:
    with Session(engine) as session:
        context_options = [
            ContextOption(id=int(context.id), name=context.name)
            for context in decision_repo.list_contexts(session)
            if context.id is not None
        ]

    def handle_submit(name: str, description: str, context_ids: list[int]) -> None:
        errors = decision_service.validate_decision_payload(name, description)
        if errors:
            show_errors(err.message for err in errors)
            return

        with Session(engine) as session:
            record = decision_repo.create_decision(
                session,
                name=name,
                description=description,
                context_ids=context_ids,
            )
        ui.navigate.to(f'{after_create_base_url}/{record.id}')

    render_decision_form(
        title='Create Decision',
        initial_name='',
        initial_description='',
        context_options=context_options,
        initial_context_ids=[],
        on_submit=handle_submit,
        on_cancel=lambda: ui.navigate.to(back_url),
    )
