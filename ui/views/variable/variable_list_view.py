from __future__ import annotations

from collections.abc import Callable

from nicegui import ui
from sqlmodel import Session

from repositories import variable_repo
from services.variable_service import variable_value_to_string
from ui.components.confirm_actions import confirm_delete_button


def render_variable_list(
    *,
    engine,
    agent_id: int | None,
    on_edit: Callable[[int], None],
    on_create: Callable[[int], None],
    on_delete: Callable[[int], None],
) -> None:
    with Session(engine) as session:
        resolved_agent_id, variables = variable_repo.list_variables(session, agent_id=agent_id)

    ui.label('Variables').classes('text-h5')

    if not variables:
        ui.label('No variables yet.')
    else:
        for variable in variables:
            value_text = variable_value_to_string(variable)
            with ui.row().classes('items-center justify-between w-full border rounded p-2'):
                ui.label(f'{variable.name} [{variable.var_type.value}] = {value_text or "<unset>"}')
                with ui.row().classes('gap-1'):
                    ui.button('Edit', on_click=lambda vid=variable.id: on_edit(int(vid))).props('flat')
                    confirm_delete_button(
                        label='Delete',
                        item_name=f'variable "{variable.name}"',
                        on_confirm=lambda vid=variable.id: on_delete(int(vid)),
                    )

    ui.button('Create Variable', on_click=lambda: on_create(resolved_agent_id), color='primary')
