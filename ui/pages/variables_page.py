from __future__ import annotations

from nicegui import ui
from sqlmodel import Session

from repositories import variable_repo
from ui.components.page_shell import page_shell
from ui.views.variable.variable_create_view import render_variable_create_view
from ui.views.variable.variable_edit_view import render_variable_edit_view
from ui.views.variable.variable_list_view import render_variable_list


def register_variable_pages(engine) -> None:
    @ui.page('/variables')
    def variables_index() -> None:
        with page_shell(title='Variables', breadcrumb_path='/variables', max_width_class='max-w-4xl'):
            render_variable_list(
                engine=engine,
                agent_id=None,
                on_edit=lambda variable_id: ui.navigate.to(f'/variables/{variable_id}/edit'),
                on_create=lambda _agent_id: ui.navigate.to('/variables/new'),
                on_delete=lambda variable_id: _delete_variable_and_refresh(engine, variable_id),
            )

    @ui.page('/variables/new')
    def variable_create() -> None:
        with page_shell(title='Create Variable', breadcrumb_path='/variables/new', max_width_class='max-w-2xl'):
            render_variable_create_view(engine=engine, agent_id=None, back_url='/variables')

    @ui.page('/variables/{variable_id}/edit')
    def variable_edit(variable_id: int) -> None:
        with page_shell(
            title='Edit Variable',
            breadcrumb_path=f'/variables/{variable_id}/edit',
            max_width_class='max-w-2xl',
        ):
            render_variable_edit_view(engine=engine, variable_id=variable_id, back_url='/variables')


def _delete_variable_and_refresh(engine, variable_id: int) -> None:
    with Session(engine) as session:
        variable_repo.delete_variable(session, variable_id)
    ui.notify('Variable deleted.', color='positive')
    ui.navigate.to('/variables')
