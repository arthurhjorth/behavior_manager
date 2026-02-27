from __future__ import annotations

from collections.abc import Callable

from nicegui import ui
from sqlmodel import Session

from repositories import decision_repo
from ui.components.confirm_actions import confirm_delete_button


def render_adapter_list(
    *,
    engine,
    decision_id: int,
    on_edit: Callable[[int], None],
    on_create: Callable[[], None],
    on_delete: Callable[[int], None],
) -> None:
    ui.label('Adapters').classes('text-h6')

    with Session(engine) as session:
        adapters = decision_repo.list_adapters(session, decision_id)
        outcomes = decision_repo.list_outcomes(session, decision_id)
    outcome_name_by_id = {outcome.id: outcome.name for outcome in outcomes}

    if not adapters:
        ui.label('No adapters yet.')
    else:
        for adapter in adapters:
            target_label = outcome_name_by_id.get(adapter.target_outcome_id, f'#{adapter.target_outcome_id}')
            label = f'{adapter.adapter_type.value} -> {target_label}'
            with ui.row().classes('items-center justify-between w-full border rounded p-2'):
                ui.label(label)
                with ui.row().classes('gap-1'):
                    ui.button('Edit', on_click=lambda aid=adapter.id: on_edit(int(aid))).props('flat')
                    confirm_delete_button(
                        label='Delete',
                        item_name=f'{adapter.adapter_type.value} adapter',
                        on_confirm=lambda aid=adapter.id: on_delete(int(aid)),
                    )

    ui.button('Add Adapter', on_click=lambda: on_create(), color='primary').props('outline')
