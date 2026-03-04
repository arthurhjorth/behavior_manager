from __future__ import annotations

import json

from nicegui import ui
from sqlmodel import Session

from repositories import decision_repo
from services import decision_service, netlogo_export_service
from ui.components.messages import show_errors
from ui.views.adapter.adapter_list_view import render_adapter_list
from ui.views.decision.decision_form_view import ContextOption, render_decision_form
from ui.views.outcome.outcome_list_view import render_outcome_list
from ui.components.confirm_actions import confirm_delete_button


def render_decision_edit_view(*, engine, decision_id: int, back_url: str) -> None:
    with Session(engine) as session:
        decision = decision_repo.get_decision(session, decision_id)
        context_options = [
            ContextOption(id=int(context.id), name=context.name)
            for context in decision_repo.list_contexts(session)
            if context.id is not None
        ]
        selected_context_ids = [
            int(context.id)
            for context in (decision.contexts if decision is not None else [])
            if context.id is not None
        ]

    if decision is None:
        ui.label('Decision not found.')
        ui.button('Back', on_click=lambda: ui.navigate.to(back_url))
        return

    with ui.column().classes('w-full gap-4'):
        with ui.row().classes('justify-end w-full gap-2'):
            ui.button('Export NetLogo', on_click=lambda: _show_netlogo_export(engine, decision_id)).props('outline')
            ui.button('Test Decision', on_click=lambda: ui.navigate.to(f'/decisions/{decision_id}/test')).props('outline')
            confirm_delete_button(
                label='Delete Decision',
                item_name=f'decision "{decision.name}"',
                on_confirm=lambda: _delete_decision(engine, decision_id, back_url),
            )

        render_decision_form(
            title=f'Edit Decision #{decision_id}',
            initial_name=decision.name,
            initial_description=decision.description,
            context_options=context_options,
            initial_context_ids=selected_context_ids,
            on_submit=lambda name, description, context_ids: _update_decision(
                engine,
                decision_id,
                name,
                description,
                context_ids,
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
            on_edit=lambda adapter_set_id: ui.navigate.to(f'/decisions/{decision_id}/adapters/{adapter_set_id}/edit'),
            on_create=lambda: ui.navigate.to(f'/decisions/{decision_id}/adapters/new'),
            on_delete=lambda adapter_set_id: _delete_adapter_set(engine, decision_id, adapter_set_id),
        )


def _update_decision(engine, decision_id: int, name: str, description: str, context_ids: list[int]) -> None:
    errors = decision_service.validate_decision_payload(name, description)
    if errors:
        show_errors(err.message for err in errors)
        return
    with Session(engine) as session:
        decision_repo.update_decision(session, decision_id, name, description, context_ids=context_ids)
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


def _delete_adapter_set(engine, decision_id: int, adapter_set_id: int) -> None:
    with Session(engine) as session:
        decision_repo.delete_adapter_set(session, adapter_set_id)
    ui.notify('Adapter set deleted.', color='positive')
    ui.navigate.to(f'/decisions/{decision_id}')


def _show_netlogo_export(engine, decision_id: int) -> None:
    try:
        with Session(engine) as session:
            code = netlogo_export_service.export_decision_reporter(session, decision_id)
    except Exception as exc:
        ui.notify(f'Could not export NetLogo: {exc}', color='negative')
        return

    with ui.dialog() as dialog, ui.card().classes('w-[90vw] max-w-5xl'):
        ui.label('NetLogo Reporter').classes('text-h6')
        code_area = ui.textarea(value=code).props('readonly').classes('w-full').style('min-height: 60vh;')
        with ui.row().classes('justify-end w-full gap-2'):
            ui.button(
                'Copy',
                on_click=lambda: ui.run_javascript(f'navigator.clipboard.writeText({json.dumps(str(code_area.value))});'),
            ).props('outline')
            ui.button('Close', on_click=dialog.close).props('outline')
    dialog.open()
