from __future__ import annotations

from nicegui import ui
from sqlmodel import Session

from repositories import decision_repo
from ui.components.page_shell import page_shell
from ui.views.context.context_list_view import render_context_list


def register_context_pages(engine) -> None:
    @ui.page('/contexts')
    def contexts_index() -> None:
        with page_shell(title='Contexts', breadcrumb_path='/contexts', max_width_class='max-w-4xl'):
            render_context_list(
                engine=engine,
                on_create=lambda name: _create_context_and_refresh(engine, name),
                on_delete=lambda context_id: _delete_context_and_refresh(engine, context_id),
            )


def _create_context_and_refresh(engine, name: str) -> None:
    with Session(engine) as session:
        decision_repo.create_context(session, name)
    ui.notify('Context created.', color='positive')
    ui.navigate.to('/contexts')


def _delete_context_and_refresh(engine, context_id: int) -> None:
    with Session(engine) as session:
        decision_repo.delete_context(session, context_id)
    ui.notify('Context deleted.', color='positive')
    ui.navigate.to('/contexts')
