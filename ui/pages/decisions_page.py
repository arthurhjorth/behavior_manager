from __future__ import annotations

from nicegui import ui
from sqlmodel import Session

from models import AdapterRecord, AdapterType, LinearCoefficientRecord
from repositories import decision_repo
from services import decision_service
from ui.components.confirm_actions import confirm_delete_button
from ui.components.messages import show_errors
from ui.views.adapter.adapter_create_picker_view import render_adapter_create_picker_view
from ui.views.adapter.binary_adapter_form_view import render_binary_adapter_form
from ui.views.adapter.coefficient_edit_view import render_coefficient_edit_view
from ui.views.adapter.coefficient_list_view import render_coefficient_list
from ui.views.adapter.linear_adapter_form_view import render_linear_adapter_form
from ui.views.decision.decision_create_view import render_decision_create_view
from ui.views.decision.decision_edit_view import render_decision_edit_view
from ui.views.decision.decision_list_view import render_decision_list
from ui.views.outcome.outcome_create_view import render_outcome_create_view
from ui.views.outcome.outcome_edit_view import render_outcome_edit_view


def register_decision_pages(engine) -> None:
    @ui.page('/decisions')
    def decisions_index() -> None:
        with ui.column().classes('w-full max-w-4xl p-6 gap-4'):
            render_decision_list(
                engine=engine,
                on_select=lambda decision_id: ui.navigate.to(f'/decisions/{decision_id}'),
                on_create=lambda: ui.navigate.to('/decisions/new'),
                on_delete=lambda decision_id: _delete_decision_and_refresh(engine, decision_id),
            )

    @ui.page('/decisions/new')
    def decision_create() -> None:
        with ui.column().classes('w-full max-w-4xl p-6 gap-4'):
            render_decision_create_view(
                engine=engine,
                back_url='/decisions',
                after_create_base_url='/decisions',
            )

    @ui.page('/decisions/{decision_id}')
    def decision_edit(decision_id: int) -> None:
        with ui.column().classes('w-full max-w-4xl p-6 gap-4'):
            render_decision_edit_view(engine=engine, decision_id=decision_id, back_url='/decisions')

    @ui.page('/decisions/{decision_id}/outcomes/new')
    def outcome_create(decision_id: int) -> None:
        with ui.column().classes('w-full max-w-2xl p-6 gap-4'):
            render_outcome_create_view(
                engine=engine,
                decision_id=decision_id,
                back_url=f'/decisions/{decision_id}',
            )

    @ui.page('/decisions/{decision_id}/outcomes/{outcome_id}/edit')
    def outcome_edit(decision_id: int, outcome_id: int) -> None:
        with ui.column().classes('w-full max-w-2xl p-6 gap-4'):
            render_outcome_edit_view(
                engine=engine,
                outcome_id=outcome_id,
                back_url=f'/decisions/{decision_id}',
            )

    @ui.page('/decisions/{decision_id}/adapters/new')
    def adapter_picker(decision_id: int) -> None:
        with ui.column().classes('w-full max-w-2xl p-6 gap-4'):
            render_adapter_create_picker_view(
                on_pick_binary=lambda: ui.navigate.to(f'/decisions/{decision_id}/adapters/new/binary'),
                on_pick_linear=lambda: ui.navigate.to(f'/decisions/{decision_id}/adapters/new/linear'),
                on_cancel=lambda: ui.navigate.to(f'/decisions/{decision_id}'),
            )

    @ui.page('/decisions/{decision_id}/adapters/new/binary')
    def binary_adapter_create(decision_id: int) -> None:
        with Session(engine) as session:
            outcome_options = _outcome_options(session, decision_id)

        def handle_submit(target_outcome_id: int | None, multiplier: float) -> None:
            errors = decision_service.validate_binary_adapter_payload(target_outcome_id, multiplier)
            if errors:
                show_errors(err.message for err in errors)
                return
            with Session(engine) as session:
                decision_repo.create_binary_adapter(
                    session,
                    decision_id=decision_id,
                    target_outcome_id=int(target_outcome_id),
                    multiplier=multiplier,
                )
            ui.navigate.to(f'/decisions/{decision_id}')

        with ui.column().classes('w-full max-w-2xl p-6 gap-4'):
            render_binary_adapter_form(
                title='Create Binary Adapter',
                outcome_options=outcome_options,
                initial_target_outcome_id=None,
                initial_multiplier=1.0,
                on_submit=handle_submit,
                on_cancel=lambda: ui.navigate.to(f'/decisions/{decision_id}'),
            )

    @ui.page('/decisions/{decision_id}/adapters/new/linear')
    def linear_adapter_create(decision_id: int) -> None:
        with Session(engine) as session:
            outcome_options = _outcome_options(session, decision_id)

        def handle_submit(
            target_outcome_id: int | None,
            intercept: float,
            min_multiplier: float,
            max_multiplier: float | None,
        ) -> None:
            errors = decision_service.validate_linear_adapter_payload(
                target_outcome_id,
                intercept,
                min_multiplier,
                max_multiplier,
            )
            if errors:
                show_errors(err.message for err in errors)
                return
            with Session(engine) as session:
                decision_repo.create_linear_adapter(
                    session,
                    decision_id=decision_id,
                    target_outcome_id=int(target_outcome_id),
                    intercept=intercept,
                    min_multiplier=min_multiplier,
                    max_multiplier=max_multiplier,
                )
            ui.navigate.to(f'/decisions/{decision_id}')

        with ui.column().classes('w-full max-w-2xl p-6 gap-4'):
            render_linear_adapter_form(
                title='Create Linear Adapter',
                outcome_options=outcome_options,
                initial_target_outcome_id=None,
                initial_intercept=1.0,
                initial_min_multiplier=0.0,
                initial_max_multiplier=None,
                on_submit=handle_submit,
                on_cancel=lambda: ui.navigate.to(f'/decisions/{decision_id}'),
            )

    @ui.page('/decisions/{decision_id}/adapters/{adapter_id}/edit')
    def adapter_edit(decision_id: int, adapter_id: int) -> None:
        with Session(engine) as session:
            adapter = session.get(AdapterRecord, adapter_id)
            outcome_options = _outcome_options(session, decision_id)

        if adapter is None:
            with ui.column().classes('w-full max-w-2xl p-6 gap-4'):
                ui.label('Adapter not found.')
                ui.button('Back', on_click=lambda: ui.navigate.to(f'/decisions/{decision_id}'))
            return

        with ui.column().classes('w-full max-w-3xl p-6 gap-4'):
            if adapter.adapter_type == AdapterType.binary:
                _render_binary_adapter_edit(engine, decision_id, adapter, outcome_options)
                return
            _render_linear_adapter_edit(engine, decision_id, adapter, outcome_options)

    @ui.page('/decisions/{decision_id}/adapters/{adapter_id}/coefficients/new')
    def coefficient_create(decision_id: int, adapter_id: int) -> None:
        with Session(engine) as session:
            variable_options = _variable_options(session, decision_id)

        def handle_submit(variable_id: int | None, coefficient: float) -> None:
            errors = decision_service.validate_coefficient_payload(variable_id)
            if errors:
                show_errors(err.message for err in errors)
                return
            with Session(engine) as session:
                decision_repo.create_coefficient(
                    session,
                    adapter_id=adapter_id,
                    variable_id=int(variable_id),
                    coefficient=coefficient,
                )
            ui.navigate.to(f'/decisions/{decision_id}/adapters/{adapter_id}/edit')

        with ui.column().classes('w-full max-w-2xl p-6 gap-4'):
            render_coefficient_edit_view(
                title='Create Coefficient',
                variable_options=variable_options,
                initial_variable_id=None,
                initial_coefficient=0.0,
                on_submit=handle_submit,
                on_cancel=lambda: ui.navigate.to(f'/decisions/{decision_id}/adapters/{adapter_id}/edit'),
            )

    @ui.page('/decisions/{decision_id}/adapters/{adapter_id}/coefficients/{coefficient_id}/edit')
    def coefficient_edit(decision_id: int, adapter_id: int, coefficient_id: int) -> None:
        with Session(engine) as session:
            coefficient = session.get(LinearCoefficientRecord, coefficient_id)
            variable_options = _variable_options(session, decision_id)

        if coefficient is None:
            with ui.column().classes('w-full max-w-2xl p-6 gap-4'):
                ui.label('Coefficient not found.')
                ui.button(
                    'Back',
                    on_click=lambda: ui.navigate.to(f'/decisions/{decision_id}/adapters/{adapter_id}/edit'),
                )
            return

        def handle_submit(variable_id: int | None, coef_value: float) -> None:
            errors = decision_service.validate_coefficient_payload(variable_id)
            if errors:
                show_errors(err.message for err in errors)
                return
            with Session(engine) as session:
                decision_repo.update_coefficient(
                    session,
                    coefficient_id=coefficient_id,
                    variable_id=int(variable_id),
                    coefficient=coef_value,
                )
            ui.navigate.to(f'/decisions/{decision_id}/adapters/{adapter_id}/edit')

        with ui.column().classes('w-full max-w-2xl p-6 gap-4'):
            render_coefficient_edit_view(
                title=f'Edit Coefficient #{coefficient_id}',
                variable_options=variable_options,
                initial_variable_id=coefficient.variable_id,
                initial_coefficient=coefficient.coefficient,
                on_submit=handle_submit,
                on_cancel=lambda: ui.navigate.to(f'/decisions/{decision_id}/adapters/{adapter_id}/edit'),
            )


def _render_binary_adapter_edit(
    engine,
    decision_id: int,
    adapter: AdapterRecord,
    outcome_options: dict[int, str],
) -> None:
    with ui.row().classes('justify-end w-full'):
        confirm_delete_button(
            label='Delete Adapter',
            item_name='adapter',
            on_confirm=lambda: _delete_adapter_and_go_back(engine, decision_id, adapter.id),
        )

    def handle_submit(target_outcome_id: int | None, multiplier: float) -> None:
        errors = decision_service.validate_binary_adapter_payload(target_outcome_id, multiplier)
        if errors:
            show_errors(err.message for err in errors)
            return
        with Session(engine) as session:
            decision_repo.update_binary_adapter(
                session,
                adapter_id=adapter.id,
                target_outcome_id=int(target_outcome_id),
                multiplier=multiplier,
            )
        ui.navigate.to(f'/decisions/{decision_id}')

    render_binary_adapter_form(
        title=f'Edit Binary Adapter #{adapter.id}',
        outcome_options=outcome_options,
        initial_target_outcome_id=adapter.target_outcome_id,
        initial_multiplier=adapter.multiplier or 1.0,
        on_submit=handle_submit,
        on_cancel=lambda: ui.navigate.to(f'/decisions/{decision_id}'),
    )


def _render_linear_adapter_edit(
    engine,
    decision_id: int,
    adapter: AdapterRecord,
    outcome_options: dict[int, str],
) -> None:
    with ui.row().classes('justify-end w-full'):
        confirm_delete_button(
            label='Delete Adapter',
            item_name='adapter',
            on_confirm=lambda: _delete_adapter_and_go_back(engine, decision_id, adapter.id),
        )

    def handle_submit(
        target_outcome_id: int | None,
        intercept: float,
        min_multiplier: float,
        max_multiplier: float | None,
    ) -> None:
        errors = decision_service.validate_linear_adapter_payload(
            target_outcome_id,
            intercept,
            min_multiplier,
            max_multiplier,
        )
        if errors:
            show_errors(err.message for err in errors)
            return
        with Session(engine) as session:
            decision_repo.update_linear_adapter(
                session,
                adapter_id=adapter.id,
                target_outcome_id=int(target_outcome_id),
                intercept=intercept,
                min_multiplier=min_multiplier,
                max_multiplier=max_multiplier,
            )
        ui.notify('Linear adapter saved.', color='positive')

    render_linear_adapter_form(
        title=f'Edit Linear Adapter #{adapter.id}',
        outcome_options=outcome_options,
        initial_target_outcome_id=adapter.target_outcome_id,
        initial_intercept=adapter.intercept or 1.0,
        initial_min_multiplier=adapter.min_multiplier or 0.0,
        initial_max_multiplier=adapter.max_multiplier,
        on_submit=handle_submit,
        on_cancel=lambda: ui.navigate.to(f'/decisions/{decision_id}'),
    )

    ui.separator()
    render_coefficient_list(
        engine=engine,
        adapter_id=adapter.id,
        on_edit=lambda coefficient_id: ui.navigate.to(
            f'/decisions/{decision_id}/adapters/{adapter.id}/coefficients/{coefficient_id}/edit'
        ),
        on_create=lambda: ui.navigate.to(f'/decisions/{decision_id}/adapters/{adapter.id}/coefficients/new'),
        on_delete=lambda coefficient_id: _delete_coefficient_and_refresh(
            engine,
            decision_id,
            adapter.id,
            coefficient_id,
        ),
    )


def _outcome_options(session: Session, decision_id: int) -> dict[int, str]:
    return {
        int(outcome.id): outcome.name
        for outcome in decision_repo.list_outcomes(session, decision_id)
        if outcome.id is not None
    }


def _variable_options(session: Session, decision_id: int) -> dict[int, str]:
    decision = decision_repo.get_decision(session, decision_id)
    if decision is None:
        return {}
    return {
        int(variable.id): variable.name
        for variable in decision_repo.list_variables(session, decision.agent_id)
        if variable.id is not None
    }


def _delete_decision_and_refresh(engine, decision_id: int) -> None:
    with Session(engine) as session:
        decision_repo.delete_decision(session, decision_id)
    ui.notify('Decision deleted.', color='positive')
    ui.navigate.to('/decisions')


def _delete_adapter_and_go_back(engine, decision_id: int, adapter_id: int) -> None:
    with Session(engine) as session:
        decision_repo.delete_adapter(session, adapter_id)
    ui.notify('Adapter deleted.', color='positive')
    ui.navigate.to(f'/decisions/{decision_id}')


def _delete_coefficient_and_refresh(engine, decision_id: int, adapter_id: int, coefficient_id: int) -> None:
    with Session(engine) as session:
        decision_repo.delete_coefficient(session, coefficient_id)
    ui.notify('Coefficient deleted.', color='positive')
    ui.navigate.to(f'/decisions/{decision_id}/adapters/{adapter_id}/edit')
