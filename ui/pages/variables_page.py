from __future__ import annotations

from nicegui import ui
from sqlmodel import Session

from repositories import variable_repo
from ui.views.variable.variable_create_view import render_variable_create_view
from ui.views.variable.variable_edit_view import render_variable_edit_view
from ui.views.variable.variable_list_view import render_variable_list


def register_variable_pages(engine) -> None:
    @ui.page('/variables')
    def variables_index() -> None:
        with ui.column().classes('w-full max-w-4xl p-6 gap-4'):
            render_variable_list(
                engine=engine,
                agent_id=None,
                on_edit=lambda variable_id: ui.navigate.to(f'/variables/{variable_id}/edit'),
                on_create=lambda _agent_id: ui.navigate.to('/variables/new'),
                on_delete=lambda variable_id: _delete_variable_and_refresh(engine, variable_id),
            )

    @ui.page('/variables/new')
    def variable_create() -> None:
        with ui.column().classes('w-full max-w-2xl p-6 gap-4'):
            render_variable_create_view(engine=engine, agent_id=None, back_url='/variables')

    @ui.page('/variables/{variable_id}/edit')
    def variable_edit(variable_id: int) -> None:
        with ui.column().classes('w-full max-w-2xl p-6 gap-4'):
            render_variable_edit_view(engine=engine, variable_id=variable_id, back_url='/variables')


def _delete_variable_and_refresh(engine, variable_id: int) -> None:
    with Session(engine) as session:
        variable_repo.delete_variable(session, variable_id)
    ui.notify('Variable deleted.', color='positive')
    ui.navigate.to('/variables')
