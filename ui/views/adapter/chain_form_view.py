from __future__ import annotations

from collections.abc import Callable

from nicegui import ui

from models import ConditionCombinator
from ui.components.form_actions import form_actions


def render_chain_form(
    *,
    title: str,
    initial_name: str,
    initial_combinator: ConditionCombinator,
    initial_order_index: int,
    on_submit: Callable[[str, ConditionCombinator, int], None],
    on_cancel: Callable[[], None],
) -> None:
    ui.label(title).classes('text-h6')
    name_input = ui.input('Chain name', value=initial_name).classes('w-full')
    combinator_select = ui.select(
        options={c.value: c.value for c in ConditionCombinator},
        value=initial_combinator.value,
        label='Combinator',
    ).classes('w-full')
    order_input = ui.number('Order index', value=initial_order_index, step=1).classes('w-full')

    def handle_submit() -> None:
        on_submit(
            (name_input.value or '').strip() or 'Chain',
            ConditionCombinator(str(combinator_select.value)),
            int(order_input.value or 0),
        )

    form_actions(on_save=handle_submit, on_cancel=on_cancel)
