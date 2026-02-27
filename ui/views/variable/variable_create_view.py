from __future__ import annotations

from nicegui import ui
from sqlmodel import Session

from models import VarType
from repositories import variable_repo
from services import variable_service
from ui.components.messages import show_errors
from ui.views.variable.variable_form_view import render_variable_form


def render_variable_create_view(*, engine, agent_id: int | None, back_url: str) -> None:
    with Session(engine) as session:
        resolved_agent_id, _ = variable_repo.list_variables(session, agent_id=agent_id)

    def handle_submit(
        name: str,
        var_type: VarType,
        raw_value: str,
        is_observer: bool,
        is_turtle: bool,
        is_patch: bool,
        is_link: bool,
        breed: str,
    ) -> None:
        errors = variable_service.validate_variable_payload(name, breed)
        if errors:
            show_errors(err.message for err in errors)
            return

        try:
            parsed_value = variable_service.parse_value(raw_value, var_type)
        except ValueError as exc:
            show_errors([str(exc)])
            return

        with Session(engine) as session:
            variable_repo.create_variable(
                session,
                agent_id=resolved_agent_id,
                name=name,
                var_type=var_type,
                value=parsed_value,
                is_observer=is_observer,
                is_turtle=is_turtle,
                is_patch=is_patch,
                is_link=is_link,
                breed=breed,
            )
        ui.navigate.to(back_url)

    render_variable_form(
        title='Create Variable',
        initial_name='',
        initial_var_type=VarType._float,
        initial_value='',
        initial_is_observer=False,
        initial_is_turtle=False,
        initial_is_patch=False,
        initial_is_link=False,
        initial_breed='',
        on_submit=handle_submit,
        on_cancel=lambda: ui.navigate.to(back_url),
    )
