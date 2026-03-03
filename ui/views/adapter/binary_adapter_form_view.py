from __future__ import annotations

from collections.abc import Callable

from nicegui import ui

from models import AdapterLikelihoodMode
from ui.components.form_actions import form_actions


def render_binary_adapter_form(
    *,
    title: str,
    outcome_options: dict[int, str],
    initial_target_outcome_id: int | None,
    initial_multiplier: float,
    initial_likelihood_mode: AdapterLikelihoodMode,
    initial_set_likelihood: float | None,
    initial_add_points: float | None,
    on_submit: Callable[[int | None, float, AdapterLikelihoodMode, float | None, float | None], None],
    on_cancel: Callable[[], None],
) -> None:
    ui.label(title).classes('text-h6')
    target_select = ui.select(
        options=outcome_options,
        value=initial_target_outcome_id,
        label='Target outcome',
    ).classes('w-full')
    mode_select = ui.select(
        options={m.value: m.value for m in AdapterLikelihoodMode},
        value=initial_likelihood_mode.value,
        label='Likelihood mode',
    ).classes('w-full')
    multiplier_input = ui.number('Multiplier (> 0)', value=initial_multiplier, min=0.0001, step=0.1).classes('w-full')
    set_like_input = ui.input(
        'Set likelihood (used in set mode)',
        value='' if initial_set_likelihood is None else str(initial_set_likelihood),
    ).classes('w-full')
    add_points_input = ui.input(
        'Add %-pts (used in add_points mode, e.g. 0.05 for +5 %-pts)',
        value='' if initial_add_points is None else str(initial_add_points),
    ).classes('w-full')

    def handle_submit() -> None:
        selected = None if target_select.value is None else int(target_select.value)
        mode = AdapterLikelihoodMode(str(mode_select.value))
        raw_set = (set_like_input.value or '').strip()
        raw_add_points = (add_points_input.value or '').strip()
        try:
            set_likelihood = float(raw_set) if raw_set else None
        except ValueError:
            ui.notify('Set likelihood must be a number.', color='negative')
            return
        try:
            add_points = float(raw_add_points) if raw_add_points else None
        except ValueError:
            ui.notify('Add %-pts must be a number.', color='negative')
            return
        on_submit(selected, float(multiplier_input.value or 1.0), mode, set_likelihood, add_points)

    form_actions(on_save=handle_submit, on_cancel=on_cancel)
