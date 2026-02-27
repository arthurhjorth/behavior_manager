from __future__ import annotations

from collections.abc import Callable

from nicegui import ui
from sqlmodel import Session

from models import AdapterRecord
from repositories import decision_repo
from ui.components.confirm_actions import confirm_delete_button


def render_coefficient_list(
    *,
    engine,
    adapter_id: int,
    on_edit: Callable[[int], None],
    on_create: Callable[[], None],
    on_delete: Callable[[int], None],
) -> None:
    ui.label('Coefficients').classes('text-subtitle1')

    with Session(engine) as session:
        coeffs = decision_repo.list_coefficients(session, adapter_id)
        adapter = session.get(AdapterRecord, adapter_id)
        variable_name_by_id: dict[int, str] = {}
        if adapter is not None:
            variables = decision_repo.list_variables(session)
            variable_name_by_id = {int(variable.id): variable.name for variable in variables if variable.id is not None}

    if not coeffs:
        ui.label('No coefficients yet.')
    else:
        for coef in coeffs:
            variable_name = variable_name_by_id.get(coef.variable_id, f'#{coef.variable_id}')
            with ui.row().classes('items-center justify-between w-full border rounded p-2'):
                ui.label(f'{variable_name}: {coef.coefficient:.3f}')
                with ui.row().classes('gap-1'):
                    ui.button('Edit', on_click=lambda cid=coef.id: on_edit(int(cid))).props('flat')
                    confirm_delete_button(
                        label='Delete',
                        item_name=f'coefficient for "{variable_name}"',
                        on_confirm=lambda cid=coef.id: on_delete(int(cid)),
                    )

    ui.button('Add Coefficient', on_click=lambda: on_create()).props('outline')
