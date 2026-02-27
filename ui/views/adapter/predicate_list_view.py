from __future__ import annotations

from collections.abc import Callable

from nicegui import ui
from sqlmodel import Session

from repositories import decision_repo
from ui.components.confirm_actions import confirm_delete_button


def render_predicate_list(
    *,
    engine,
    chain_id: int,
    on_edit: Callable[[int], None],
    on_create: Callable[[], None],
    on_delete: Callable[[int], None],
) -> None:
    ui.label('Predicates').classes('text-subtitle1')

    with Session(engine) as session:
        chain = decision_repo.get_chain(session, chain_id)
        predicates = decision_repo.list_predicates(session, chain_id)
        variable_name_by_id = {
            int(variable.id): variable.name
            for variable in decision_repo.list_variables(session)
            if variable.id is not None
        }

    if chain is not None:
        ui.label(f'Group: {chain.name} ({chain.combinator.value})').classes('text-body2 text-grey-7')

    if not predicates:
        ui.label('No predicates yet.')
    else:
        for predicate in predicates:
            var_name = variable_name_by_id.get(predicate.variable_id, f'#{predicate.variable_id}')
            value_label = _value_label(predicate)
            with ui.row().classes('items-center justify-between w-full border rounded p-2'):
                ui.label(f'{var_name} {predicate.operator.value} {value_label}')
                with ui.row().classes('gap-1'):
                    ui.button('Edit', on_click=lambda pid=predicate.id: on_edit(int(pid))).props('flat')
                    confirm_delete_button(
                        label='Delete',
                        item_name=f'predicate on "{var_name}"',
                        on_confirm=lambda pid=predicate.id: on_delete(int(pid)),
                    )

    ui.button('Add Predicate', on_click=lambda: on_create()).props('outline')


def _value_label(predicate) -> str:
    if predicate.value_int is not None:
        return str(predicate.value_int)
    if predicate.value_float is not None:
        return str(predicate.value_float)
    if predicate.value_bool is not None:
        return 'true' if predicate.value_bool else 'false'
    return '<unset>'
