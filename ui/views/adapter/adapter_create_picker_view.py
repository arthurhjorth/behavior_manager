from __future__ import annotations

from collections.abc import Callable

from nicegui import ui


def render_adapter_create_picker_view(
    *,
    on_pick_binary: Callable[[], None],
    on_pick_linear: Callable[[], None],
    on_cancel: Callable[[], None],
) -> None:
    ui.label('Choose Adapter Type').classes('text-h6')
    with ui.row().classes('gap-2'):
        ui.button('Binary Adapter', on_click=lambda: on_pick_binary(), color='primary')
        ui.button('Linear Adapter', on_click=lambda: on_pick_linear(), color='primary')
    ui.button('Back', on_click=lambda: on_cancel(), color='secondary').props('flat')
