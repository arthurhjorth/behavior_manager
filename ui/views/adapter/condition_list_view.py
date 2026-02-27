from __future__ import annotations

from collections.abc import Callable

from nicegui import ui
from sqlmodel import Session

from models import AdapterRecord
from repositories import decision_repo
from ui.components.confirm_actions import confirm_delete_button


def render_condition_list(
    *,
    engine,
    adapter_id: int,
    on_edit: Callable[[int], None],
    on_create: Callable[[], None],
    on_delete: Callable[[int], None],
) -> None:
    ui.label('Conditions').classes('text-subtitle1')

    with Session(engine) as session:
        conditions = decision_repo.list_conditions(session, adapter_id)
        adapter = session.get(AdapterRecord, adapter_id)
        variable_name_by_id: dict[int, str] = {}
        if adapter is not None:
            variables = decision_repo.list_variables(session)
            variable_name_by_id = {int(variable.id): variable.name for variable in variables if variable.id is not None}

    if not conditions:
        ui.label('No conditions yet. Adapter always applies.')
    else:
        for condition in conditions:
            variable_name = variable_name_by_id.get(condition.variable_id, f'#{condition.variable_id}')
            value_label = _condition_value_label(condition)
            with ui.row().classes('items-center justify-between w-full border rounded p-2'):
                ui.label(f'{variable_name} {condition.operator.value} {value_label}')
                with ui.row().classes('gap-1'):
                    ui.button('Edit', on_click=lambda cid=condition.id: on_edit(int(cid))).props('flat')
                    confirm_delete_button(
                        label='Delete',
                        item_name=f'condition on "{variable_name}"',
                        on_confirm=lambda cid=condition.id: on_delete(int(cid)),
                    )

    ui.button('Add Condition', on_click=lambda: on_create()).props('outline')


def _condition_value_label(condition) -> str:
    if condition.value_int is not None:
        return str(condition.value_int)
    if condition.value_float is not None:
        return str(condition.value_float)
    if condition.value_bool is not None:
        return 'true' if condition.value_bool else 'false'
    return '<unset>'
