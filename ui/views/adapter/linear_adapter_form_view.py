from __future__ import annotations

from collections.abc import Callable

from nicegui import ui

from models import AdapterLikelihoodMode
from ui.components.form_actions import form_actions


def render_linear_adapter_form(
    *,
    title: str,
    outcome_options: dict[int, str],
    initial_target_outcome_id: int | None,
    initial_intercept: float,
    initial_min_multiplier: float,
    initial_max_multiplier: float | None,
    initial_likelihood_mode: AdapterLikelihoodMode,
    on_submit: Callable[[int | None, float, float, float | None, AdapterLikelihoodMode], None],
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
    intercept_input = ui.number('Intercept', value=initial_intercept, step=0.1).classes('w-full')
    min_input = ui.number('Min multiplier', value=initial_min_multiplier, step=0.1).classes('w-full')
    max_text = '' if initial_max_multiplier is None else str(initial_max_multiplier)
    max_input = ui.input('Max multiplier (optional)', value=max_text).classes('w-full')

    def handle_submit() -> None:
        raw = (max_input.value or '').strip()
        max_multiplier = float(raw) if raw else None
        selected = None if target_select.value is None else int(target_select.value)
        on_submit(
            selected,
            float(intercept_input.value or 0.0),
            float(min_input.value or 0.0),
            max_multiplier,
            AdapterLikelihoodMode(str(mode_select.value)),
        )

    form_actions(on_save=handle_submit, on_cancel=on_cancel)
