from __future__ import annotations

from collections.abc import Callable

from nicegui import ui


def confirm_delete_button(*, label: str, item_name: str, on_confirm: Callable[[], None]) -> None:
    def open_dialog() -> None:
        with ui.dialog() as dialog, ui.card().classes('w-96'):
            ui.label(f'Delete {item_name}?').classes('text-h6')
            ui.label('This cannot be undone.')
            with ui.row().classes('justify-end w-full gap-2'):
                ui.button('Cancel', on_click=dialog.close).props('flat')

                def confirm() -> None:
                    dialog.close()
                    on_confirm()

                ui.button('Delete', on_click=confirm, color='negative')
        dialog.open()

    ui.button(label, on_click=open_dialog, color='negative').props('flat')
