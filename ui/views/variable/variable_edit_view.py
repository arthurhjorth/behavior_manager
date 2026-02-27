from __future__ import annotations

from nicegui import ui
from sqlmodel import Session

from models import VarType
from repositories import variable_repo
from services import variable_service
from ui.components.confirm_actions import confirm_delete_button
from ui.components.messages import show_errors
from ui.views.variable.variable_form_view import render_variable_form


def render_variable_edit_view(*, engine, variable_id: int, back_url: str) -> None:
    with Session(engine) as session:
        row = variable_repo.get_variable(session, variable_id)

    if row is None:
        ui.label('Variable not found.')
        ui.button('Back', on_click=lambda: ui.navigate.to(back_url))
        return

    with ui.row().classes('justify-end w-full'):
        confirm_delete_button(
            label='Delete Variable',
            item_name=f'variable "{row.name}"',
            on_confirm=lambda: _delete_variable(engine, variable_id, back_url),
        )

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
            variable_repo.update_variable(
                session,
                variable_id=variable_id,
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
        title=f'Edit Variable #{variable_id}',
        initial_name=row.name,
        initial_var_type=row.var_type,
        initial_value=variable_service.variable_value_to_string(row),
        initial_is_observer=row.is_observer,
        initial_is_turtle=row.is_turtle,
        initial_is_patch=row.is_patch,
        initial_is_link=row.is_link,
        initial_breed=row.breed,
        on_submit=handle_submit,
        on_cancel=lambda: ui.navigate.to(back_url),
    )


def _delete_variable(engine, variable_id: int, back_url: str) -> None:
    with Session(engine) as session:
        variable_repo.delete_variable(session, variable_id)
    ui.notify('Variable deleted.', color='positive')
    ui.navigate.to(back_url)
