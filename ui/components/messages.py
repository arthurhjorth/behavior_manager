from __future__ import annotations

from collections.abc import Iterable

from nicegui import ui


def show_errors(messages: Iterable[str]) -> None:
    for message in messages:
        ui.notify(message, color='negative')
