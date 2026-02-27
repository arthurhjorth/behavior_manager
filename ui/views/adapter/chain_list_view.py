from __future__ import annotations

from collections.abc import Callable

from nicegui import ui
from sqlmodel import Session

from repositories import decision_repo
from ui.components.confirm_actions import confirm_delete_button


def render_chain_list(
    *,
    engine,
    adapter_id: int,
    on_open: Callable[[int], None],
    on_create: Callable[[], None],
    on_delete: Callable[[int], None],
) -> None:
    ui.label('Predicate Groups (Chains)').classes('text-subtitle1')

    with Session(engine) as session:
        chains = decision_repo.list_chains(session, adapter_id)
        variable_names = {
            int(variable.id): variable.name
            for variable in decision_repo.list_variables(session)
            if variable.id is not None
        }

    if not chains:
        ui.label('No chains yet.')
    else:
        for chain in chains:
            with Session(engine) as session:
                predicates = decision_repo.list_predicates(session, int(chain.id))
            condition_text = _chain_condition_text(chain.combinator.value, predicates, variable_names)
            with ui.row().classes('items-center justify-between w-full border rounded p-2'):
                ui.label(condition_text)
                with ui.row().classes('gap-1'):
                    ui.button('Open', on_click=lambda cid=chain.id: on_open(int(cid))).props('flat')
                    confirm_delete_button(
                        label='Delete',
                        item_name=f'chain "{chain.name}"',
                        on_confirm=lambda cid=chain.id: on_delete(int(cid)),
                    )

    ui.button('Add Chain', on_click=lambda: on_create()).props('outline')


def _chain_condition_text(combinator: str, predicates, variable_names: dict[int, str]) -> str:
    if not predicates:
        return 'if <no predicates>'

    parts = []
    for predicate in predicates:
        variable_name = variable_names.get(predicate.variable_id, f'#{predicate.variable_id}')
        value = _predicate_value(predicate)
        parts.append(f'{variable_name} {predicate.operator.value} {value}')

    joiner = ' AND ' if combinator == 'all' else ' OR '
    return f'if {joiner.join(parts)}'


def _predicate_value(predicate) -> str:
    if predicate.value_int is not None:
        return str(predicate.value_int)
    if predicate.value_float is not None:
        return str(predicate.value_float)
    if predicate.value_bool is not None:
        return 'true' if predicate.value_bool else 'false'
    return '<unset>'
