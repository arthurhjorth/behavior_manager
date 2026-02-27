from __future__ import annotations

from collections.abc import Callable

from nicegui import ui


def form_actions(on_save: Callable[[], None], on_cancel: Callable[[], None]) -> None:
    with ui.row().classes('gap-2'):
        ui.button('Save', on_click=lambda: on_save(), color='primary')
        ui.button('Cancel', on_click=lambda: on_cancel(), color='secondary')
