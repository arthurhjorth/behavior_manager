from __future__ import annotations

from collections.abc import Callable

from nicegui import ui

from ui.components.form_actions import form_actions


def render_outcome_form(
    *,
    title: str,
    initial_name: str,
    initial_likelihood: float | None,
    on_submit: Callable[[str, float | None], None],
    on_cancel: Callable[[], None],
) -> None:
    ui.label(title).classes('text-h6')
    name_input = ui.input('Outcome name', value=initial_name).classes('w-full')
    likelihood_input = ui.input(
        'Likelihood (optional)',
        value='' if initial_likelihood is None else str(initial_likelihood),
    ).classes('w-full')

    def handle_submit() -> None:
        raw_value = (likelihood_input.value or '').strip()
        try:
            likelihood: float | None = float(raw_value) if raw_value else None
        except ValueError:
            ui.notify('Likelihood must be a number.', color='negative')
            return
        on_submit((name_input.value or '').strip(), likelihood)

    form_actions(on_save=handle_submit, on_cancel=on_cancel)
