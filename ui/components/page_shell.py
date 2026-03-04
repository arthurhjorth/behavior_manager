from __future__ import annotations

from contextlib import contextmanager
from typing import Optional

from nicegui import ui


@contextmanager
def page_shell(
    *,
    title: str,
    breadcrumb_path: str,
    max_width_class: str = 'max-w-4xl',
    breadcrumb_items: Optional[list[tuple[str, str | None]]] = None,
):
    with ui.column().classes(f'w-full {max_width_class} p-6 gap-4'):
        _render_header(title)
        _render_breadcrumbs(breadcrumb_path, breadcrumb_items)
        ui.separator()
        yield


def _render_header(title: str) -> None:
    with ui.row().classes('w-full items-center justify-between'):
        with ui.row().classes('items-center gap-3'):
            ui.label('Behavior Manager').classes('text-h6')
            ui.label(title).classes('text-subtitle1 text-grey-7')

        with ui.row().classes('items-center gap-3'):
            ui.link('Home', '/')
            ui.link('Studies', '/studies/')
            ui.link('Decisions', '/decisions')
            ui.link('Variables', '/variables')
            ui.link('Contexts', '/contexts')
            ui.link('Datasets', '/datasets')


def _render_breadcrumbs(path: str, breadcrumb_items: Optional[list[tuple[str, str | None]]] = None) -> None:
    if breadcrumb_items:
        with ui.row().classes('items-center gap-2 text-body2 text-grey-7'):
            for index, (label, href) in enumerate(breadcrumb_items):
                if index > 0:
                    ui.label('>')
                if href:
                    _crumb_link(label, href)
                else:
                    ui.label(label).classes('text-weight-medium text-black')
        return

    clean = path.strip()
    if not clean.startswith('/'):
        clean = '/' + clean

    segments = [segment for segment in clean.strip('/').split('/') if segment]

    with ui.row().classes('items-center gap-2 text-body2 text-grey-7'):
        _crumb_link('Home', '/')

        current_parts: list[str] = []
        for index, segment in enumerate(segments):
            ui.label('>')
            current_parts.append(segment)
            target = '/' + '/'.join(current_parts)
            label = _segment_label(segment)
            is_last = index == len(segments) - 1
            if is_last:
                ui.label(label).classes('text-weight-medium text-black')
            else:
                _crumb_link(label, target)


def _crumb_link(label: str, href: str) -> None:
    ui.link(label, href).classes('text-grey-8')


def _segment_label(segment: str) -> str:
    if segment.isdigit():
        return f'#{segment}'
    return segment.replace('_', ' ').replace('-', ' ').title()
