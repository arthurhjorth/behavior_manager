from __future__ import annotations

from nicegui import ui
from sqlmodel import Session

from models import (
    AdapterRecord,
    AdapterSetRecord,
    AdapterLikelihoodMode,
    AdapterType,
    ConditionCombinator,
    ConditionOperator,
    LinearCoefficientRecord,
    PredicateRecord,
)
from repositories import decision_repo
from services import decision_service
from ui.components.confirm_actions import confirm_delete_button
from ui.components.messages import show_errors
from ui.components.page_shell import page_shell
from ui.views.adapter.adapter_create_picker_view import render_adapter_create_picker_view
from ui.views.adapter.binary_adapter_form_view import render_binary_adapter_form
from ui.views.adapter.chain_form_view import render_chain_form
from ui.views.adapter.chain_list_view import render_chain_list
from ui.views.adapter.condition_form_view import render_condition_form
from ui.views.adapter.coefficient_edit_view import render_coefficient_edit_view
from ui.views.adapter.coefficient_list_view import render_coefficient_list
from ui.views.adapter.linear_adapter_form_view import render_linear_adapter_form
from ui.views.adapter.predicate_list_view import render_predicate_list
from ui.views.decision.decision_create_view import render_decision_create_view
from ui.views.decision.decision_edit_view import render_decision_edit_view
from ui.views.decision.decision_list_view import render_decision_list
from ui.views.decision.decision_test_view import render_decision_test_view
from ui.views.outcome.outcome_create_view import render_outcome_create_view
from ui.views.outcome.outcome_edit_view import render_outcome_edit_view


def register_decision_pages(engine) -> None:
    @ui.page('/decisions')
    def decisions_index() -> None:
        with page_shell(title='Decisions', breadcrumb_path='/decisions', max_width_class='max-w-4xl'):
            render_decision_list(
                engine=engine,
                on_select=lambda decision_id: ui.navigate.to(f'/decisions/{decision_id}'),
                on_create=lambda: ui.navigate.to('/decisions/new'),
                on_delete=lambda decision_id: _delete_decision_and_refresh(engine, decision_id),
            )

    @ui.page('/decisions/new')
    def decision_create() -> None:
        with page_shell(title='Create Decision', breadcrumb_path='/decisions/new', max_width_class='max-w-4xl'):
            render_decision_create_view(
                engine=engine,
                back_url='/decisions',
                after_create_base_url='/decisions',
            )

    @ui.page('/decisions/{decision_id}')
    def decision_edit(decision_id: int) -> None:
        with Session(engine) as session:
            decision = decision_repo.get_decision(session, decision_id)
            decision_label = decision.name if decision else f'#{decision_id}'
        with page_shell(
            title='Edit Decision',
            breadcrumb_path=f'/decisions/{decision_id}',
            max_width_class='max-w-4xl',
            breadcrumb_items=[
                ('Home', '/'),
                ('Decisions', '/decisions'),
                (decision_label, None),
            ],
        ):
            render_decision_edit_view(engine=engine, decision_id=decision_id, back_url='/decisions')

    @ui.page('/decisions/{decision_id}/test')
    def decision_test(decision_id: int) -> None:
        with Session(engine) as session:
            decision = decision_repo.get_decision(session, decision_id)
            decision_label = decision.name if decision else f'#{decision_id}'
        with page_shell(
            title='Test Decision',
            breadcrumb_path=f'/decisions/{decision_id}/test',
            max_width_class='max-w-4xl',
            breadcrumb_items=[
                ('Home', '/'),
                ('Decisions', '/decisions'),
                (decision_label, f'/decisions/{decision_id}'),
                ('Test', None),
            ],
        ):
            render_decision_test_view(
                engine=engine,
                decision_id=decision_id,
                back_url=f'/decisions/{decision_id}',
            )

    @ui.page('/decisions/{decision_id}/outcomes/new')
    def outcome_create(decision_id: int) -> None:
        with page_shell(
            title='Create Outcome',
            breadcrumb_path=f'/decisions/{decision_id}/outcomes/new',
            max_width_class='max-w-2xl',
        ):
            render_outcome_create_view(
                engine=engine,
                decision_id=decision_id,
                back_url=f'/decisions/{decision_id}',
            )

    @ui.page('/decisions/{decision_id}/outcomes/{outcome_id}/edit')
    def outcome_edit(decision_id: int, outcome_id: int) -> None:
        with page_shell(
            title='Edit Outcome',
            breadcrumb_path=f'/decisions/{decision_id}/outcomes/{outcome_id}/edit',
            max_width_class='max-w-2xl',
        ):
            render_outcome_edit_view(
                engine=engine,
                outcome_id=outcome_id,
                back_url=f'/decisions/{decision_id}',
            )

    @ui.page('/decisions/{decision_id}/adapters/new')
    def adapter_picker(decision_id: int) -> None:
        with Session(engine) as session:
            adapter_set = decision_repo.create_adapter_set(
                session,
                decision_id=decision_id,
                name='New Rule Set',
                order_index=0,
            )
            adapter_set_id = int(adapter_set.id)
        ui.navigate.to(f'/decisions/{decision_id}/adapters/{adapter_set_id}/edit')

    @ui.page('/decisions/{decision_id}/adapters/new/binary')
    def binary_adapter_create(decision_id: int) -> None:
        with Session(engine) as session:
            outcome_options = _outcome_options(session, decision_id)

        def handle_submit(
            target_outcome_id: int | None,
            multiplier: float,
            likelihood_mode: AdapterLikelihoodMode,
            set_likelihood: float | None,
            add_points: float | None,
        ) -> None:
            errors = decision_service.validate_binary_adapter_payload(
                target_outcome_id,
                multiplier,
                likelihood_mode,
                set_likelihood,
                add_points,
            )
            if errors:
                show_errors(err.message for err in errors)
                return
            with Session(engine) as session:
                decision_repo.create_binary_adapter(
                    session,
                    decision_id=decision_id,
                    target_outcome_id=int(target_outcome_id),
                    multiplier=multiplier,
                    likelihood_mode=likelihood_mode,
                    set_likelihood=set_likelihood,
                    add_points=add_points,
                )
            ui.navigate.to(f'/decisions/{decision_id}')

        with page_shell(
            title='Create Binary Adapter',
            breadcrumb_path=f'/decisions/{decision_id}/adapters/new/binary',
            max_width_class='max-w-2xl',
        ):
            render_binary_adapter_form(
                title='Create Binary Adapter',
                outcome_options=outcome_options,
                initial_target_outcome_id=None,
                initial_multiplier=1.0,
                initial_likelihood_mode=AdapterLikelihoodMode.multiply,
                initial_set_likelihood=None,
                initial_add_points=None,
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
            likelihood_mode: AdapterLikelihoodMode,
        ) -> None:
            errors = decision_service.validate_linear_adapter_payload(
                target_outcome_id,
                intercept,
                min_multiplier,
                max_multiplier,
                likelihood_mode,
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
                    likelihood_mode=likelihood_mode,
                )
            ui.navigate.to(f'/decisions/{decision_id}')

        with page_shell(
            title='Create Linear Adapter',
            breadcrumb_path=f'/decisions/{decision_id}/adapters/new/linear',
            max_width_class='max-w-2xl',
        ):
            render_linear_adapter_form(
                title='Create Linear Adapter',
                outcome_options=outcome_options,
                initial_target_outcome_id=None,
                initial_intercept=1.0,
                initial_min_multiplier=0.0,
                initial_max_multiplier=None,
                initial_likelihood_mode=AdapterLikelihoodMode.multiply,
                on_submit=handle_submit,
                on_cancel=lambda: ui.navigate.to(f'/decisions/{decision_id}'),
            )

    @ui.page('/decisions/{decision_id}/adapters/{adapter_id}/edit')
    def adapter_edit(decision_id: int, adapter_id: int) -> None:
        with Session(engine) as session:
            decision = decision_repo.get_decision(session, decision_id)
            adapter_set = session.get(AdapterSetRecord, adapter_id)
            outcome_options = _outcome_options(session, decision_id)
            effects = decision_repo.list_adapters(session, adapter_set_id=adapter_id)
            decision_label = decision.name if decision else f'#{decision_id}'
            adapter_label = adapter_set.name if adapter_set else f'#{adapter_id}'

        breadcrumbs = [
            ('Home', '/'),
            ('Decisions', '/decisions'),
            (decision_label, f'/decisions/{decision_id}'),
            (adapter_label, None),
        ]

        if adapter_set is None:
            with page_shell(
                title='Edit Adapter Set',
                breadcrumb_path=f'/decisions/{decision_id}/adapters/{adapter_id}/edit',
                max_width_class='max-w-2xl',
                breadcrumb_items=breadcrumbs,
            ):
                ui.label('Adapter set not found.')
                ui.button('Back', on_click=lambda: ui.navigate.to(f'/decisions/{decision_id}'))
            return

        with page_shell(
            title='Edit Adapter Set',
            breadcrumb_path=f'/decisions/{decision_id}/adapters/{adapter_id}/edit',
            max_width_class='max-w-3xl',
            breadcrumb_items=breadcrumbs,
        ):
            _render_adapter_set_edit(engine, decision_id, adapter_set, effects, outcome_options)

    @ui.page('/decisions/{decision_id}/adapters/{adapter_id}/effects/new/binary')
    def binary_effect_create(decision_id: int, adapter_id: int) -> None:
        with Session(engine) as session:
            outcome_options = _outcome_options(session, decision_id)

        def handle_submit(
            target_outcome_id: int | None,
            multiplier: float,
            likelihood_mode: AdapterLikelihoodMode,
            set_likelihood: float | None,
            add_points: float | None,
        ) -> None:
            errors = decision_service.validate_binary_adapter_payload(
                target_outcome_id,
                multiplier,
                likelihood_mode,
                set_likelihood,
                add_points,
            )
            if errors:
                show_errors(err.message for err in errors)
                return
            with Session(engine) as session:
                decision_repo.create_binary_adapter(
                    session,
                    adapter_set_id=adapter_id,
                    target_outcome_id=int(target_outcome_id),
                    multiplier=multiplier,
                    likelihood_mode=likelihood_mode,
                    set_likelihood=set_likelihood,
                    add_points=add_points,
                )
            ui.navigate.to(f'/decisions/{decision_id}/adapters/{adapter_id}/edit')

        with page_shell(
            title='Create Effect (Binary)',
            breadcrumb_path=f'/decisions/{decision_id}/adapters/{adapter_id}/effects/new/binary',
            max_width_class='max-w-2xl',
        ):
            render_binary_adapter_form(
                title='Create Binary Effect',
                outcome_options=outcome_options,
                initial_target_outcome_id=None,
                initial_multiplier=1.0,
                initial_likelihood_mode=AdapterLikelihoodMode.multiply,
                initial_set_likelihood=None,
                initial_add_points=None,
                on_submit=handle_submit,
                on_cancel=lambda: ui.navigate.to(f'/decisions/{decision_id}/adapters/{adapter_id}/edit'),
            )

    @ui.page('/decisions/{decision_id}/adapters/{adapter_id}/effects/new/linear')
    def linear_effect_create(decision_id: int, adapter_id: int) -> None:
        with Session(engine) as session:
            outcome_options = _outcome_options(session, decision_id)

        def handle_submit(
            target_outcome_id: int | None,
            intercept: float,
            min_multiplier: float,
            max_multiplier: float | None,
            likelihood_mode: AdapterLikelihoodMode,
        ) -> None:
            errors = decision_service.validate_linear_adapter_payload(
                target_outcome_id,
                intercept,
                min_multiplier,
                max_multiplier,
                likelihood_mode,
            )
            if errors:
                show_errors(err.message for err in errors)
                return
            with Session(engine) as session:
                decision_repo.create_linear_adapter(
                    session,
                    adapter_set_id=adapter_id,
                    target_outcome_id=int(target_outcome_id),
                    intercept=intercept,
                    min_multiplier=min_multiplier,
                    max_multiplier=max_multiplier,
                    likelihood_mode=likelihood_mode,
                )
            ui.navigate.to(f'/decisions/{decision_id}/adapters/{adapter_id}/edit')

        with page_shell(
            title='Create Effect (Linear)',
            breadcrumb_path=f'/decisions/{decision_id}/adapters/{adapter_id}/effects/new/linear',
            max_width_class='max-w-2xl',
        ):
            render_linear_adapter_form(
                title='Create Linear Effect',
                outcome_options=outcome_options,
                initial_target_outcome_id=None,
                initial_intercept=1.0,
                initial_min_multiplier=0.0,
                initial_max_multiplier=None,
                initial_likelihood_mode=AdapterLikelihoodMode.multiply,
                on_submit=handle_submit,
                on_cancel=lambda: ui.navigate.to(f'/decisions/{decision_id}/adapters/{adapter_id}/edit'),
            )

    @ui.page('/decisions/{decision_id}/adapters/{adapter_id}/effects/{effect_id}/edit')
    def effect_edit(decision_id: int, adapter_id: int, effect_id: int) -> None:
        with Session(engine) as session:
            effect = session.get(AdapterRecord, effect_id)
            outcome_options = _outcome_options(session, decision_id)
        if effect is None:
            with page_shell(
                title='Edit Effect',
                breadcrumb_path=f'/decisions/{decision_id}/adapters/{adapter_id}/effects/{effect_id}/edit',
                max_width_class='max-w-2xl',
            ):
                ui.label('Effect not found.')
            return
        with page_shell(
            title='Edit Effect',
            breadcrumb_path=f'/decisions/{decision_id}/adapters/{adapter_id}/effects/{effect_id}/edit',
            max_width_class='max-w-3xl',
        ):
            if effect.adapter_type == AdapterType.binary:
                _render_binary_adapter_edit(engine, decision_id, adapter_id, effect, outcome_options)
            else:
                _render_linear_adapter_edit(engine, decision_id, adapter_id, effect, outcome_options)

    @ui.page('/decisions/{decision_id}/adapters/{adapter_id}/effects/{effect_id}/coefficients/new')
    def coefficient_create(decision_id: int, adapter_id: int, effect_id: int) -> None:
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
                    adapter_id=effect_id,
                    variable_id=int(variable_id),
                    coefficient=coefficient,
                )
            ui.navigate.to(f'/decisions/{decision_id}/adapters/{adapter_id}/effects/{effect_id}/edit')

        with page_shell(
            title='Create Coefficient',
            breadcrumb_path=f'/decisions/{decision_id}/adapters/{adapter_id}/effects/{effect_id}/coefficients/new',
            max_width_class='max-w-2xl',
        ):
            render_coefficient_edit_view(
                title='Create Coefficient',
                variable_options=variable_options,
                initial_variable_id=None,
                initial_coefficient=0.0,
                on_submit=handle_submit,
                on_cancel=lambda: ui.navigate.to(f'/decisions/{decision_id}/adapters/{adapter_id}/effects/{effect_id}/edit'),
            )

    @ui.page('/decisions/{decision_id}/adapters/{adapter_id}/effects/{effect_id}/coefficients/{coefficient_id}/edit')
    def coefficient_edit(decision_id: int, adapter_id: int, effect_id: int, coefficient_id: int) -> None:
        with Session(engine) as session:
            coefficient = session.get(LinearCoefficientRecord, coefficient_id)
            variable_options = _variable_options(session, decision_id)

        if coefficient is None:
            with page_shell(
                title='Edit Coefficient',
                breadcrumb_path=f'/decisions/{decision_id}/adapters/{adapter_id}/coefficients/{coefficient_id}/edit',
                max_width_class='max-w-2xl',
            ):
                ui.label('Coefficient not found.')
                ui.button(
                    'Back',
                    on_click=lambda: ui.navigate.to(f'/decisions/{decision_id}/adapters/{adapter_id}/effects/{effect_id}/edit'),
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
            ui.navigate.to(f'/decisions/{decision_id}/adapters/{adapter_id}/effects/{effect_id}/edit')

        with page_shell(
            title='Edit Coefficient',
            breadcrumb_path=f'/decisions/{decision_id}/adapters/{adapter_id}/effects/{effect_id}/coefficients/{coefficient_id}/edit',
            max_width_class='max-w-2xl',
        ):
            render_coefficient_edit_view(
                title=f'Edit Coefficient #{coefficient_id}',
                variable_options=variable_options,
                initial_variable_id=coefficient.variable_id,
                initial_coefficient=coefficient.coefficient,
                on_submit=handle_submit,
                on_cancel=lambda: ui.navigate.to(f'/decisions/{decision_id}/adapters/{adapter_id}/effects/{effect_id}/edit'),
            )

    @ui.page('/decisions/{decision_id}/adapters/{adapter_id}/conditions/new')
    def condition_create(decision_id: int, adapter_id: int) -> None:
        with Session(engine) as session:
            variable_options = _variable_options(session, decision_id)
            variable_rows = _variable_rows_by_id(session, decision_id)

        def handle_submit(
            variable_id: int | None,
            operator: ConditionOperator | None,
            raw_value: str,
        ) -> None:
            errors = decision_service.validate_condition_payload(variable_id, operator, raw_value)
            if errors:
                show_errors(err.message for err in errors)
                return

            variable = variable_rows.get(int(variable_id))
            if variable is None:
                show_errors(['Variable not found.'])
                return
            if variable.var_type.value == 'bool' and operator in {
                ConditionOperator.gt,
                ConditionOperator.gte,
                ConditionOperator.lt,
                ConditionOperator.lte,
            }:
                show_errors(['Boolean variables only support eq/ne operators.'])
                return

            try:
                value_int, value_float, value_bool = decision_service.parse_condition_value(
                    variable.var_type,
                    raw_value,
                )
            except ValueError as exc:
                show_errors([str(exc)])
                return

            with Session(engine) as session:
                decision_repo.create_condition(
                    session,
                    adapter_id=adapter_id,
                    variable_id=int(variable_id),
                    operator=operator,
                    value_int=value_int,
                    value_float=value_float,
                    value_bool=value_bool,
                )
            ui.navigate.to(f'/decisions/{decision_id}/adapters/{adapter_id}/edit')

        with page_shell(
            title='Create Condition',
            breadcrumb_path=f'/decisions/{decision_id}/adapters/{adapter_id}/conditions/new',
            max_width_class='max-w-2xl',
        ):
            render_condition_form(
                title='Create Predicate',
                variable_options=variable_options,
                initial_variable_id=None,
                initial_operator=ConditionOperator.gt,
                initial_value='',
                on_submit=handle_submit,
                on_cancel=lambda: ui.navigate.to(f'/decisions/{decision_id}/adapters/{adapter_id}/edit'),
            )

    @ui.page('/decisions/{decision_id}/adapters/{adapter_id}/conditions/{condition_id}/edit')
    def condition_edit(decision_id: int, adapter_id: int, condition_id: int) -> None:
        with Session(engine) as session:
            condition = session.get(PredicateRecord, condition_id)
            variable_options = _variable_options(session, decision_id)
            variable_rows = _variable_rows_by_id(session, decision_id)

        if condition is None:
            with page_shell(
                title='Edit Condition',
                breadcrumb_path=f'/decisions/{decision_id}/adapters/{adapter_id}/conditions/{condition_id}/edit',
                max_width_class='max-w-2xl',
            ):
                ui.label('Condition not found.')
                ui.button(
                    'Back',
                    on_click=lambda: ui.navigate.to(f'/decisions/{decision_id}/adapters/{adapter_id}/edit'),
                )
            return

        def handle_submit(
            variable_id: int | None,
            operator: ConditionOperator | None,
            raw_value: str,
        ) -> None:
            errors = decision_service.validate_condition_payload(variable_id, operator, raw_value)
            if errors:
                show_errors(err.message for err in errors)
                return

            variable = variable_rows.get(int(variable_id))
            if variable is None:
                show_errors(['Variable not found.'])
                return
            if variable.var_type.value == 'bool' and operator in {
                ConditionOperator.gt,
                ConditionOperator.gte,
                ConditionOperator.lt,
                ConditionOperator.lte,
            }:
                show_errors(['Boolean variables only support eq/ne operators.'])
                return

            try:
                value_int, value_float, value_bool = decision_service.parse_condition_value(
                    variable.var_type,
                    raw_value,
                )
            except ValueError as exc:
                show_errors([str(exc)])
                return

            with Session(engine) as session:
                decision_repo.update_condition(
                    session,
                    condition_id=condition_id,
                    variable_id=int(variable_id),
                    operator=operator,
                    value_int=value_int,
                    value_float=value_float,
                    value_bool=value_bool,
                )
            ui.navigate.to(f'/decisions/{decision_id}/adapters/{adapter_id}/edit')

        with page_shell(
            title='Edit Condition',
            breadcrumb_path=f'/decisions/{decision_id}/adapters/{adapter_id}/conditions/{condition_id}/edit',
            max_width_class='max-w-2xl',
        ):
            render_condition_form(
                title=f'Edit Predicate #{condition_id}',
                variable_options=variable_options,
                initial_variable_id=condition.variable_id,
                initial_operator=condition.operator,
                initial_value=_condition_value_label(condition),
                on_submit=handle_submit,
                on_cancel=lambda: ui.navigate.to(f'/decisions/{decision_id}/adapters/{adapter_id}/edit'),
            )

    @ui.page('/decisions/{decision_id}/adapters/{adapter_id}/chains/new')
    def chain_create(decision_id: int, adapter_id: int) -> None:
        def handle_submit(name: str, combinator: ConditionCombinator, order_index: int) -> None:
            with Session(engine) as session:
                decision_repo.create_chain(
                    session,
                    adapter_set_id=adapter_id,
                    name=name,
                    combinator=combinator,
                    order_index=order_index,
                )
            ui.navigate.to(f'/decisions/{decision_id}/adapters/{adapter_id}/edit')

        with page_shell(
            title='Create Predicate Group',
            breadcrumb_path=f'/decisions/{decision_id}/adapters/{adapter_id}/chains/new',
            max_width_class='max-w-2xl',
        ):
            render_chain_form(
                title='Create Predicate Group',
                initial_name='New Group',
                initial_combinator=ConditionCombinator.all,
                initial_order_index=0,
                on_submit=handle_submit,
                on_cancel=lambda: ui.navigate.to(f'/decisions/{decision_id}/adapters/{adapter_id}/edit'),
            )

    @ui.page('/decisions/{decision_id}/adapters/{adapter_id}/chains/{chain_id}/edit')
    def chain_edit(decision_id: int, adapter_id: int, chain_id: int) -> None:
        with Session(engine) as session:
            chain = decision_repo.get_chain(session, chain_id)

        if chain is None:
            with page_shell(
                title='Edit Predicate Group',
                breadcrumb_path=f'/decisions/{decision_id}/adapters/{adapter_id}/chains/{chain_id}/edit',
                max_width_class='max-w-2xl',
            ):
                ui.label('Predicate group not found.')
                ui.button('Back', on_click=lambda: ui.navigate.to(f'/decisions/{decision_id}/adapters/{adapter_id}/edit'))
            return

        def handle_submit(name: str, combinator: ConditionCombinator, order_index: int) -> None:
            with Session(engine) as session:
                decision_repo.update_chain(
                    session,
                    chain_id=chain_id,
                    name=name,
                    combinator=combinator,
                    order_index=order_index,
                )
            ui.navigate.to(f'/decisions/{decision_id}/adapters/{adapter_id}/chains/{chain_id}/edit')

        with page_shell(
            title='Edit Predicate Group',
            breadcrumb_path=f'/decisions/{decision_id}/adapters/{adapter_id}/chains/{chain_id}/edit',
            max_width_class='max-w-3xl',
        ):
            render_chain_form(
                title=f'Edit Predicate Group #{chain_id}',
                initial_name=chain.name,
                initial_combinator=chain.combinator,
                initial_order_index=chain.order_index,
                on_submit=handle_submit,
                on_cancel=lambda: ui.navigate.to(f'/decisions/{decision_id}/adapters/{adapter_id}/edit'),
            )
            ui.separator()
            render_predicate_list(
                engine=engine,
                chain_id=chain_id,
                on_edit=lambda predicate_id: ui.navigate.to(
                    f'/decisions/{decision_id}/adapters/{adapter_id}/chains/{chain_id}/predicates/{predicate_id}/edit'
                ),
                on_create=lambda: ui.navigate.to(
                    f'/decisions/{decision_id}/adapters/{adapter_id}/chains/{chain_id}/predicates/new'
                ),
                on_delete=lambda predicate_id: _delete_predicate_and_refresh(
                    engine,
                    decision_id,
                    adapter_id,
                    chain_id,
                    predicate_id,
                ),
            )

    @ui.page('/decisions/{decision_id}/adapters/{adapter_id}/chains/{chain_id}/predicates/new')
    def predicate_create(decision_id: int, adapter_id: int, chain_id: int) -> None:
        with Session(engine) as session:
            variable_options = _variable_options(session, decision_id)
            variable_rows = _variable_rows_by_id(session, decision_id)

        def handle_submit(variable_id: int | None, operator: ConditionOperator | None, raw_value: str) -> None:
            errors = decision_service.validate_condition_payload(variable_id, operator, raw_value)
            if errors:
                show_errors(err.message for err in errors)
                return
            variable = variable_rows.get(int(variable_id))
            if variable is None:
                show_errors(['Variable not found.'])
                return
            try:
                value_int, value_float, value_bool = decision_service.parse_condition_value(variable.var_type, raw_value)
            except ValueError as exc:
                show_errors([str(exc)])
                return
            with Session(engine) as session:
                decision_repo.create_predicate(
                    session,
                    chain_id=chain_id,
                    variable_id=int(variable_id),
                    operator=operator,
                    value_int=value_int,
                    value_float=value_float,
                    value_bool=value_bool,
                )
            ui.navigate.to(f'/decisions/{decision_id}/adapters/{adapter_id}/chains/{chain_id}/edit')

        with page_shell(
            title='Create Predicate',
            breadcrumb_path=f'/decisions/{decision_id}/adapters/{adapter_id}/chains/{chain_id}/predicates/new',
            max_width_class='max-w-2xl',
        ):
            render_condition_form(
                title='Create Predicate',
                variable_options=variable_options,
                initial_variable_id=None,
                initial_operator=ConditionOperator.gt,
                initial_value='',
                on_submit=handle_submit,
                on_cancel=lambda: ui.navigate.to(f'/decisions/{decision_id}/adapters/{adapter_id}/chains/{chain_id}/edit'),
            )

    @ui.page('/decisions/{decision_id}/adapters/{adapter_id}/chains/{chain_id}/predicates/{predicate_id}/edit')
    def predicate_edit(decision_id: int, adapter_id: int, chain_id: int, predicate_id: int) -> None:
        with Session(engine) as session:
            predicate = session.get(PredicateRecord, predicate_id)
            variable_options = _variable_options(session, decision_id)
            variable_rows = _variable_rows_by_id(session, decision_id)
        if predicate is None:
            with page_shell(
                title='Edit Predicate',
                breadcrumb_path=f'/decisions/{decision_id}/adapters/{adapter_id}/chains/{chain_id}/predicates/{predicate_id}/edit',
                max_width_class='max-w-2xl',
            ):
                ui.label('Predicate not found.')
            return

        def handle_submit(variable_id: int | None, operator: ConditionOperator | None, raw_value: str) -> None:
            errors = decision_service.validate_condition_payload(variable_id, operator, raw_value)
            if errors:
                show_errors(err.message for err in errors)
                return
            variable = variable_rows.get(int(variable_id))
            if variable is None:
                show_errors(['Variable not found.'])
                return
            try:
                value_int, value_float, value_bool = decision_service.parse_condition_value(variable.var_type, raw_value)
            except ValueError as exc:
                show_errors([str(exc)])
                return
            with Session(engine) as session:
                decision_repo.update_predicate(
                    session,
                    predicate_id=predicate_id,
                    variable_id=int(variable_id),
                    operator=operator,
                    value_int=value_int,
                    value_float=value_float,
                    value_bool=value_bool,
                )
            ui.navigate.to(f'/decisions/{decision_id}/adapters/{adapter_id}/chains/{chain_id}/edit')

        with page_shell(
            title='Edit Predicate',
            breadcrumb_path=f'/decisions/{decision_id}/adapters/{adapter_id}/chains/{chain_id}/predicates/{predicate_id}/edit',
            max_width_class='max-w-2xl',
        ):
            render_condition_form(
                title=f'Edit Predicate #{predicate_id}',
                variable_options=variable_options,
                initial_variable_id=predicate.variable_id,
                initial_operator=predicate.operator,
                initial_value=_condition_value_label(predicate),
                on_submit=handle_submit,
                on_cancel=lambda: ui.navigate.to(f'/decisions/{decision_id}/adapters/{adapter_id}/chains/{chain_id}/edit'),
            )


def _render_adapter_set_edit(
    engine,
    decision_id: int,
    adapter_set: AdapterSetRecord,
    effects: list[AdapterRecord],
    outcome_options: dict[int, str],
) -> None:
    with ui.row().classes('justify-end w-full'):
        confirm_delete_button(
            label='Delete Adapter Set',
            item_name=f'adapter set \"{adapter_set.name}\"',
            on_confirm=lambda: _delete_adapter_set_and_go_back(engine, decision_id, adapter_set.id),
        )

    set_name = ui.input('Set name', value=adapter_set.name).classes('w-full')
    set_order = ui.number('Set order', value=adapter_set.order_index, step=1).classes('w-full')
    ui.button(
        'Save Set',
        on_click=lambda: _save_adapter_set(engine, int(adapter_set.id), str(set_name.value or 'Rule Set'), int(set_order.value or 0)),
        color='primary',
    ).props('outline')

    ui.separator()
    ui.label('Effects').classes('text-h6')
    for effect in effects:
        target_label = outcome_options.get(effect.target_outcome_id, f'#{effect.target_outcome_id}')
        effect_text = _effect_summary_text(effect, target_label)
        with ui.row().classes('items-center justify-between w-full border rounded p-2'):
            ui.label(effect_text)
            with ui.row().classes('gap-1'):
                ui.button(
                    'Edit',
                    on_click=lambda eid=effect.id: ui.navigate.to(
                        f'/decisions/{decision_id}/adapters/{adapter_set.id}/effects/{eid}/edit'
                    ),
                ).props('flat')
                confirm_delete_button(
                    label='Delete',
                    item_name='effect',
                    on_confirm=lambda eid=effect.id: _delete_effect_and_refresh(engine, decision_id, adapter_set.id, int(eid)),
                )
    with ui.row().classes('gap-2'):
        ui.button(
            'Add Binary Effect',
            on_click=lambda: ui.navigate.to(f'/decisions/{decision_id}/adapters/{adapter_set.id}/effects/new/binary'),
            color='primary',
        ).props('outline')
        ui.button(
            'Add Linear Effect',
            on_click=lambda: ui.navigate.to(f'/decisions/{decision_id}/adapters/{adapter_set.id}/effects/new/linear'),
            color='primary',
        ).props('outline')

    ui.separator()
    render_chain_list(
        engine=engine,
        adapter_id=adapter_set.id,
        on_open=lambda chain_id: ui.navigate.to(
            f'/decisions/{decision_id}/adapters/{adapter_set.id}/chains/{chain_id}/edit'
        ),
        on_create=lambda: ui.navigate.to(f'/decisions/{decision_id}/adapters/{adapter_set.id}/chains/new'),
        on_delete=lambda chain_id: _delete_chain_and_refresh(engine, decision_id, adapter_set.id, chain_id),
    )


def _render_binary_adapter_edit(
    engine,
    decision_id: int,
    adapter_set_id: int,
    adapter: AdapterRecord,
    outcome_options: dict[int, str],
) -> None:
    with ui.row().classes('justify-end w-full'):
        confirm_delete_button(
            label='Delete Effect',
            item_name='effect',
            on_confirm=lambda: _delete_effect_and_refresh(engine, decision_id, adapter_set_id, adapter.id),
        )

    def handle_submit(
        target_outcome_id: int | None,
        multiplier: float,
        likelihood_mode: AdapterLikelihoodMode,
        set_likelihood: float | None,
        add_points: float | None,
    ) -> None:
        errors = decision_service.validate_binary_adapter_payload(
            target_outcome_id,
            multiplier,
            likelihood_mode,
            set_likelihood,
            add_points,
        )
        if errors:
            show_errors(err.message for err in errors)
            return
        with Session(engine) as session:
            decision_repo.update_binary_adapter(
                session,
                adapter_id=adapter.id,
                target_outcome_id=int(target_outcome_id),
                multiplier=multiplier,
                likelihood_mode=likelihood_mode,
                set_likelihood=set_likelihood,
                add_points=add_points,
            )
        ui.navigate.to(f'/decisions/{decision_id}/adapters/{adapter_set_id}/effects/{adapter.id}/edit')

    render_binary_adapter_form(
        title=f'Edit Binary Adapter #{adapter.id}',
        outcome_options=outcome_options,
        initial_target_outcome_id=adapter.target_outcome_id,
        initial_multiplier=adapter.multiplier or 1.0,
        initial_likelihood_mode=adapter.likelihood_mode,
        initial_set_likelihood=adapter.set_likelihood,
        initial_add_points=adapter.add_points,
        on_submit=handle_submit,
        on_cancel=lambda: ui.navigate.to(f'/decisions/{decision_id}/adapters/{adapter_set_id}/edit'),
    )


def _render_linear_adapter_edit(
    engine,
    decision_id: int,
    adapter_set_id: int,
    adapter: AdapterRecord,
    outcome_options: dict[int, str],
) -> None:
    with ui.row().classes('justify-end w-full'):
        confirm_delete_button(
            label='Delete Effect',
            item_name='effect',
            on_confirm=lambda: _delete_effect_and_refresh(engine, decision_id, adapter_set_id, adapter.id),
        )

    def handle_submit(
        target_outcome_id: int | None,
        intercept: float,
        min_multiplier: float,
        max_multiplier: float | None,
        likelihood_mode: AdapterLikelihoodMode,
    ) -> None:
        errors = decision_service.validate_linear_adapter_payload(
            target_outcome_id,
            intercept,
            min_multiplier,
            max_multiplier,
            likelihood_mode,
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
                likelihood_mode=likelihood_mode,
            )
        ui.notify('Linear effect saved.', color='positive')
        ui.navigate.to(f'/decisions/{decision_id}/adapters/{adapter_set_id}/effects/{adapter.id}/edit')

    render_linear_adapter_form(
        title=f'Edit Linear Adapter #{adapter.id}',
        outcome_options=outcome_options,
        initial_target_outcome_id=adapter.target_outcome_id,
        initial_intercept=adapter.intercept or 1.0,
        initial_min_multiplier=adapter.min_multiplier or 0.0,
        initial_max_multiplier=adapter.max_multiplier,
        initial_likelihood_mode=adapter.likelihood_mode,
        on_submit=handle_submit,
        on_cancel=lambda: ui.navigate.to(f'/decisions/{decision_id}/adapters/{adapter_set_id}/edit'),
    )

    ui.separator()
    render_coefficient_list(
        engine=engine,
        adapter_id=adapter.id,
        on_edit=lambda coefficient_id: ui.navigate.to(
            f'/decisions/{decision_id}/adapters/{adapter_set_id}/effects/{adapter.id}/coefficients/{coefficient_id}/edit'
        ),
        on_create=lambda: ui.navigate.to(f'/decisions/{decision_id}/adapters/{adapter_set_id}/effects/{adapter.id}/coefficients/new'),
        on_delete=lambda coefficient_id: _delete_coefficient_and_refresh(
            engine,
            decision_id,
            adapter_set_id,
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
    return {
        int(variable.id): variable.name
        for variable in decision_repo.list_variables(session)
        if variable.id is not None
    }


def _variable_rows_by_id(session: Session, decision_id: int):
    return {
        int(variable.id): variable
        for variable in decision_repo.list_variables(session)
        if variable.id is not None
    }


def _condition_value_label(condition: PredicateRecord) -> str:
    if condition.value_int is not None:
        return str(condition.value_int)
    if condition.value_float is not None:
        return str(condition.value_float)
    if condition.value_bool is not None:
        return 'true' if condition.value_bool else 'false'
    return ''


def _effect_summary_text(effect: AdapterRecord, target_label: str) -> str:
    if effect.adapter_type == AdapterType.binary:
        if effect.likelihood_mode == AdapterLikelihoodMode.set:
            value = effect.set_likelihood if effect.set_likelihood is not None else '<unset>'
            return f'set {target_label} {value}'
        if effect.likelihood_mode == AdapterLikelihoodMode.add_points:
            value = effect.add_points if effect.add_points is not None else '<unset>'
            return f'add {target_label} by {value} %-pts'
        if effect.likelihood_mode == AdapterLikelihoodMode.probability_multiply:
            value = effect.multiplier if effect.multiplier is not None else '<unset>'
            return f'multiply probability of {target_label} by {value}'
        value = effect.multiplier if effect.multiplier is not None else '<unset>'
        return f'multiply {target_label} by {value}'

    if effect.likelihood_mode == AdapterLikelihoodMode.set:
        return f'set {target_label} { _linear_value_summary(effect) }'
    if effect.likelihood_mode == AdapterLikelihoodMode.add_points:
        return f'add {target_label} by { _linear_value_summary(effect) } %-pts'
    if effect.likelihood_mode == AdapterLikelihoodMode.probability_multiply:
        return f'multiply probability of {target_label} by { _linear_value_summary(effect) }'
    return f'multiply {target_label} by { _linear_value_summary(effect) }'


def _linear_value_summary(effect: AdapterRecord) -> str:
    intercept = effect.intercept if effect.intercept is not None else 0.0
    minimum = effect.min_multiplier if effect.min_multiplier is not None else 0.0
    maximum = 'none' if effect.max_multiplier is None else str(effect.max_multiplier)
    return f'linear(intercept={intercept}, min={minimum}, max={maximum})'


def _delete_decision_and_refresh(engine, decision_id: int) -> None:
    with Session(engine) as session:
        decision_repo.delete_decision(session, decision_id)
    ui.notify('Decision deleted.', color='positive')
    ui.navigate.to('/decisions')


def _delete_adapter_and_go_back(engine, decision_id: int, adapter_id: int) -> None:
    with Session(engine) as session:
        decision_repo.delete_adapter(session, adapter_id)
    ui.notify('Effect deleted.', color='positive')
    ui.navigate.to(f'/decisions/{decision_id}')


def _delete_coefficient_and_refresh(
    engine,
    decision_id: int,
    adapter_set_id: int,
    effect_id: int,
    coefficient_id: int,
) -> None:
    with Session(engine) as session:
        decision_repo.delete_coefficient(session, coefficient_id)
    ui.notify('Coefficient deleted.', color='positive')
    ui.navigate.to(f'/decisions/{decision_id}/adapters/{adapter_set_id}/effects/{effect_id}/edit')


def _delete_condition_and_refresh(engine, decision_id: int, adapter_id: int, condition_id: int) -> None:
    with Session(engine) as session:
        decision_repo.delete_condition(session, condition_id)
    ui.notify('Condition deleted.', color='positive')
    ui.navigate.to(f'/decisions/{decision_id}/adapters/{adapter_id}/edit')


def _delete_chain_and_refresh(engine, decision_id: int, adapter_id: int, chain_id: int) -> None:
    with Session(engine) as session:
        decision_repo.delete_chain(session, chain_id)
    ui.notify('Predicate group deleted.', color='positive')
    ui.navigate.to(f'/decisions/{decision_id}/adapters/{adapter_id}/edit')


def _delete_predicate_and_refresh(
    engine,
    decision_id: int,
    adapter_id: int,
    chain_id: int,
    predicate_id: int,
) -> None:
    with Session(engine) as session:
        decision_repo.delete_predicate(session, predicate_id)
    ui.notify('Predicate deleted.', color='positive')
    ui.navigate.to(f'/decisions/{decision_id}/adapters/{adapter_id}/chains/{chain_id}/edit')


def _save_adapter_set(engine, adapter_set_id: int, name: str, order_index: int) -> None:
    with Session(engine) as session:
        decision_repo.update_adapter_set(session, adapter_set_id=adapter_set_id, name=name, order_index=order_index)
    ui.notify('Adapter set saved.', color='positive')


def _delete_adapter_set_and_go_back(engine, decision_id: int, adapter_set_id: int) -> None:
    with Session(engine) as session:
        decision_repo.delete_adapter_set(session, adapter_set_id)
    ui.notify('Adapter set deleted.', color='positive')
    ui.navigate.to(f'/decisions/{decision_id}')


def _delete_effect_and_refresh(engine, decision_id: int, adapter_set_id: int, effect_id: int) -> None:
    with Session(engine) as session:
        decision_repo.delete_adapter(session, effect_id)
    ui.notify('Effect deleted.', color='positive')
    ui.navigate.to(f'/decisions/{decision_id}/adapters/{adapter_set_id}/edit')
