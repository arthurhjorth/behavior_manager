from __future__ import annotations

from pathlib import Path
from nicegui import app, ui
from nicegui.events import UploadEventArguments
from sqlmodel import Session

from models import (
    AdapterLikelihoodMode,
    ConditionOperator,
    Study,
    VarType,
    create_study,
    get_engine,
    init_db,
    list_studies,
)
from repositories import decision_repo, variable_repo
from services import decision_service, variable_service
from ui.components.confirm_actions import confirm_delete_button
from ui.components.page_shell import page_shell
from ui.pages.contexts_page import register_context_pages
from ui.pages.datasets_page import register_dataset_pages
from ui.pages.decisions_page import register_decision_pages
from ui.pages.variables_page import register_variable_pages
from ui.views.adapter.adapter_list_view import render_adapter_list
from ui.views.decision.decision_form_view import ContextOption, render_decision_form


STUDIES_DIR = Path('studies')
STUDIES_DIR.mkdir(parents=True, exist_ok=True)
init_db()
ENGINE = get_engine()
register_decision_pages(ENGINE)
register_variable_pages(ENGINE)
register_context_pages(ENGINE)
register_dataset_pages(ENGINE)


def _seed_baseline_decision() -> None:
    with Session(ENGINE) as session:
        existing = [d for d in decision_repo.list_decisions(session) if d.name == 'choose burger type in cafeteria']
        if not existing:
            decision = decision_repo.create_decision(
                session,
                name='choose burger type in cafeteria',
                description='Seeded baseline cafeteria burger choice.',
                context_ids=[],
            )

            agent = decision_repo.ensure_agent(session)
            variables_by_name = {
                variable.name: variable
                for variable in decision_repo.list_variables(session, agent_id=int(agent.id))
            }

            reducer_var = variables_by_name.get('reducer')
            if reducer_var is None:
                reducer_var = variable_repo.create_variable(
                    session,
                    agent_id=int(agent.id),
                    name='reducer',
                    var_type=VarType._bool,
                    value=None,
                    is_observer=False,
                    is_turtle=False,
                    is_patch=False,
                    is_link=False,
                    breed='',
                )

            vegetarian_default_var = variables_by_name.get('vegetarian default')
            if vegetarian_default_var is None:
                vegetarian_default_var = variable_repo.create_variable(
                    session,
                    agent_id=int(agent.id),
                    name='vegetarian default',
                    var_type=VarType._bool,
                    value=None,
                    is_observer=False,
                    is_turtle=False,
                    is_patch=False,
                    is_link=False,
                    breed='',
                )

            meat = decision_repo.create_outcome(session, int(decision.id), 'meat', likelihood=None)
            veggy = decision_repo.create_outcome(session, int(decision.id), 'veggy', likelihood=None)

            # if reducer eq false then set meat 977; set veggy 23
            set_a = decision_repo.create_adapter_set(
                session,
                decision_id=int(decision.id),
                name='baseline reducer false',
                order_index=0,
            )
            chain_a = decision_repo.ensure_default_chain(session, int(set_a.id))
            decision_repo.create_predicate(
                session,
                chain_id=int(chain_a.id),
                variable_id=int(reducer_var.id),
                operator=ConditionOperator.eq,
                value_bool=False,
            )
            decision_repo.create_binary_adapter(
                session,
                adapter_set_id=int(set_a.id),
                target_outcome_id=int(meat.id),
                multiplier=1.0,
                likelihood_mode=AdapterLikelihoodMode.set,
                set_likelihood=977.0,
                order_index=0,
            )
            decision_repo.create_binary_adapter(
                session,
                adapter_set_id=int(set_a.id),
                target_outcome_id=int(veggy.id),
                multiplier=1.0,
                likelihood_mode=AdapterLikelihoodMode.set,
                set_likelihood=23.0,
                order_index=1,
            )

            # if reducer eq true then set meat 667; set veggy 333
            set_b = decision_repo.create_adapter_set(
                session,
                decision_id=int(decision.id),
                name='baseline reducer true',
                order_index=1,
            )
            chain_b = decision_repo.ensure_default_chain(session, int(set_b.id))
            decision_repo.create_predicate(
                session,
                chain_id=int(chain_b.id),
                variable_id=int(reducer_var.id),
                operator=ConditionOperator.eq,
                value_bool=True,
            )
            decision_repo.create_binary_adapter(
                session,
                adapter_set_id=int(set_b.id),
                target_outcome_id=int(meat.id),
                multiplier=1.0,
                likelihood_mode=AdapterLikelihoodMode.set,
                set_likelihood=667.0,
                order_index=0,
            )
            decision_repo.create_binary_adapter(
                session,
                adapter_set_id=int(set_b.id),
                target_outcome_id=int(veggy.id),
                multiplier=1.0,
                likelihood_mode=AdapterLikelihoodMode.set,
                set_likelihood=333.0,
                order_index=1,
            )

            # if reducer eq true AND vegetarian default eq true then multiply probability of veggy by 1.589
            set_c = decision_repo.create_adapter_set(
                session,
                decision_id=int(decision.id),
                name='baseline veggy boost reduced',
                order_index=2,
            )
            chain_c = decision_repo.ensure_default_chain(session, int(set_c.id))
            decision_repo.create_predicate(
                session,
                chain_id=int(chain_c.id),
                variable_id=int(reducer_var.id),
                operator=ConditionOperator.eq,
                value_bool=True,
                order_index=0,
            )
            decision_repo.create_predicate(
                session,
                chain_id=int(chain_c.id),
                variable_id=int(vegetarian_default_var.id),
                operator=ConditionOperator.eq,
                value_bool=True,
                order_index=1,
            )
            decision_repo.create_binary_adapter(
                session,
                adapter_set_id=int(set_c.id),
                target_outcome_id=int(veggy.id),
                multiplier=1.589,
                likelihood_mode=AdapterLikelihoodMode.probability_multiply,
                set_likelihood=None,
                order_index=0,
            )

            # if reducer ne true AND vegetarian default eq true then multiply probability of veggy by 6.13
            set_d = decision_repo.create_adapter_set(
                session,
                decision_id=int(decision.id),
                name='baseline veggy boost non-reduced',
                order_index=3,
            )
            chain_d = decision_repo.ensure_default_chain(session, int(set_d.id))
            decision_repo.create_predicate(
                session,
                chain_id=int(chain_d.id),
                variable_id=int(reducer_var.id),
                operator=ConditionOperator.ne,
                value_bool=True,
                order_index=0,
            )
            decision_repo.create_predicate(
                session,
                chain_id=int(chain_d.id),
                variable_id=int(vegetarian_default_var.id),
                operator=ConditionOperator.eq,
                value_bool=True,
                order_index=1,
            )
            decision_repo.create_binary_adapter(
                session,
                adapter_set_id=int(set_d.id),
                target_outcome_id=int(veggy.id),
                multiplier=6.13,
                likelihood_mode=AdapterLikelihoodMode.probability_multiply,
                set_likelihood=None,
                order_index=0,
            )

        existing_lunch = [d for d in decision_repo.list_decisions(session) if d.name == 'choose lunch at work cafeteria']
        if not existing_lunch:
            decision = decision_repo.create_decision(
                session,
                name='choose lunch at work cafeteria',
                description='Seeded baseline lunch choice at work.',
                context_ids=[],
            )

            meat = decision_repo.create_outcome(session, int(decision.id), 'meat', likelihood=None)
            vegetarian = decision_repo.create_outcome(session, int(decision.id), 'vegetarian', likelihood=None)

            baseline_set = decision_repo.create_adapter_set(
                session,
                decision_id=int(decision.id),
                name='baseline',
                order_index=0,
            )
            baseline_set_id = int(baseline_set.id)

            decision_repo.create_binary_adapter(
                session,
                adapter_set_id=baseline_set_id,
                target_outcome_id=int(meat.id),
                multiplier=1.0,
                likelihood_mode=AdapterLikelihoodMode.set,
                set_likelihood=9.0,
                order_index=0,
            )
            decision_repo.create_binary_adapter(
                session,
                adapter_set_id=baseline_set_id,
                target_outcome_id=int(vegetarian.id),
                multiplier=1.0,
                likelihood_mode=AdapterLikelihoodMode.set,
                set_likelihood=1.0,
                order_index=1,
            )


_seed_baseline_decision()


def _pdf_files() -> list[Path]:
    return sorted(
        [path for path in STUDIES_DIR.iterdir() if path.is_file() and path.suffix.lower() == '.pdf'],
        key=lambda path: path.name.lower(),
    )


def _safe_destination(filename: str) -> Path:
    base_name = Path(filename).name
    candidate = STUDIES_DIR / base_name
    if not candidate.exists():
        return candidate

    stem = candidate.stem
    suffix = candidate.suffix
    index = 1
    while True:
        renamed = STUDIES_DIR / f'{stem}_{index}{suffix}'
        if not renamed.exists():
            return renamed
        index += 1


@ui.page('/')
def index() -> None:
    with page_shell(title='Home', breadcrumb_path='/', max_width_class='max-w-3xl'):
        ui.label('Choose a section').classes('text-body1')
        ui.link('Go to studies', '/studies/')
        ui.link('Go to decisions', '/decisions')
        ui.link('Go to variables', '/variables')
        ui.link('Go to contexts', '/contexts')
        ui.link('Go to datasets', '/datasets')


@ui.page('/studies/')
def studies_page() -> None:
    with page_shell(title='Studies', breadcrumb_path='/studies/', max_width_class='max-w-3xl'):
        status = ui.label('Upload PDF studies to populate this list and DB.').classes('text-body2')
        list_container = ui.column().classes('gap-2')

        def render_list() -> None:
            list_container.clear()
            with Session(ENGINE) as session:
                studies = list_studies(session)
            if not studies:
                with list_container:
                    ui.label('No studies uploaded yet.')
                return
            with list_container:
                for study in studies:
                    with ui.row().classes('w-full items-center justify-between border rounded p-2'):
                        if study.file_path:
                            ui.label(f'{study.name} ({Path(study.file_path).name})')
                        else:
                            ui.label(study.name)
                        ui.button('View', on_click=lambda sid=study.id: ui.navigate.to(f'/studies/{int(sid)}')).props('flat')

        async def handle_upload(event: UploadEventArguments) -> None:
            filename = Path(event.file.name).name
            if Path(filename).suffix.lower() != '.pdf':
                status.set_text('Upload rejected: only .pdf files are allowed.')
                return

            destination = _safe_destination(filename)
            await event.file.save(destination)
            with Session(ENGINE) as session:
                create_study(session, name=destination.stem, file_path=str(destination))
            status.set_text(f'Uploaded: {destination.name}')
            render_list()

        ui.upload(on_upload=handle_upload, auto_upload=True).props('accept=.pdf')
        render_list()


@ui.page('/studies/{study_id}')
def study_view(study_id: int) -> None:
    with Session(ENGINE) as session:
        study = session.get(Study, study_id)

    breadcrumb_items = [
        ('Home', '/'),
        ('Studies', '/studies/'),
        (study.name if study else f'#{study_id}', None),
    ]
    with page_shell(
        title='View Study',
        breadcrumb_path=f'/studies/{study_id}',
        max_width_class='max-w-none',
        breadcrumb_items=breadcrumb_items,
    ):
        if study is None:
            ui.label('Study not found.')
            ui.button('Back', on_click=lambda: ui.navigate.to('/studies/'))
            return

        if not study.file_path:
            ui.label('Study has no file path.')
            ui.button('Back', on_click=lambda: ui.navigate.to('/studies/'))
            return

        static_path = app.add_static_file(local_file=str(Path(study.file_path).resolve()))
        with ui.row().classes('w-full items-start').style('gap: 1rem; flex-wrap: nowrap; align-items: flex-start;'):
            with ui.column().classes('min-h-[82vh] border rounded p-2 gap-3').style('flex: 0 0 46%; max-width: 46%;'):
                _render_study_workflow_column(study_id)
            with ui.column().style('flex: 0 0 46%; max-width: 46%;'):
                ui.element('embed').props(f'src={static_path} type=application/pdf').style('width:100%;height:82vh;')


def _render_study_workflow_column(study_id: int) -> None:
    ui.label('Build Decision').classes('text-h6')
    ui.label('Create decisions, variables, and adapter sets while reading the study.').classes('text-caption text-grey-7')

    with Session(ENGINE) as session:
        contexts = decision_repo.list_contexts(session)
        decisions = decision_repo.list_decisions(session)
        agent_id, variables = variable_repo.list_variables(session, agent_id=None)

    context_options = [
        ContextOption(id=int(context.id), name=context.name)
        for context in contexts
        if context.id is not None
    ]

    with ui.expansion('Decision', value=True).classes('w-full'):
        render_decision_form(
            title='Create Decision',
            initial_name='',
            initial_description='',
            context_options=context_options,
            initial_context_ids=[],
            on_submit=lambda name, description, context_ids: _create_decision_from_study(
                study_id,
                name,
                description,
                context_ids,
            ),
            on_cancel=lambda: ui.navigate.to(f'/studies/{study_id}'),
        )

        ui.separator()
        ui.label('Existing decisions').classes('text-caption text-grey-7')
        if not decisions:
            ui.label('No decisions yet.').classes('text-body2')
        else:
            for decision in decisions:
                with ui.row().classes('w-full items-center justify-between'):
                    ui.label(decision.name).classes('text-body2')
                    with ui.row().classes('gap-1'):
                        ui.button('Open', on_click=lambda did=decision.id: ui.navigate.to(f'/decisions/{int(did)}')).props('flat')
                        ui.button('Test', on_click=lambda did=decision.id: ui.navigate.to(f'/decisions/{int(did)}/test')).props('flat')

    with ui.expansion('Variables', value=False).classes('w-full'):
        name_input = ui.input('Variable name').classes('w-full')
        type_select = ui.select(
            {var_type.value: var_type.value for var_type in variable_service.VarType},
            value=variable_service.VarType._float.value,
            label='Type',
        ).classes('w-full')
        value_input = ui.input('Default value (optional)').classes('w-full')

        def handle_add_variable() -> None:
            name = (name_input.value or '').strip()
            raw_type = str(type_select.value)
            raw_value = str(value_input.value or '')
            errors = variable_service.validate_variable_payload(name, '')
            if errors:
                for error in errors:
                    ui.notify(error.message, color='negative')
                return
            try:
                var_type = variable_service.parse_var_type(raw_type)
                parsed_value = variable_service.parse_value(raw_value, var_type)
            except Exception as exc:
                ui.notify(str(exc), color='negative')
                return
            with Session(ENGINE) as session:
                variable_repo.create_variable(
                    session,
                    agent_id=agent_id,
                    name=name,
                    var_type=var_type,
                    value=parsed_value,
                    is_observer=False,
                    is_turtle=False,
                    is_patch=False,
                    is_link=False,
                    breed='',
                )
            ui.notify('Variable created.', color='positive')
            ui.navigate.to(f'/studies/{study_id}')

        ui.button('Add Variable', on_click=handle_add_variable, color='primary').props('outline')
        ui.separator()
        if not variables:
            ui.label('No variables yet.').classes('text-body2')
        else:
            for variable in variables:
                value_text = variable_service.variable_value_to_string(variable) or '<unset>'
                with ui.row().classes('w-full items-center justify-between border rounded p-2'):
                    ui.label(f'{variable.name} [{variable.var_type.value}] = {value_text}').classes('text-body2')
                    confirm_delete_button(
                        label='Delete',
                        item_name=f'variable "{variable.name}"',
                        on_confirm=lambda vid=variable.id: _delete_variable_from_study(study_id, int(vid)),
                    )

    with ui.expansion('Adapters', value=True).classes('w-full'):
        if not decisions:
            ui.label('Create a decision first.').classes('text-body2')
            return

        decision_options = {int(decision.id): decision.name for decision in decisions if decision.id is not None}
        initial_decision_id = next(iter(decision_options.keys()))
        selected_decision = ui.select(decision_options, value=initial_decision_id, label='Decision').classes('w-full')
        adapter_container = ui.column().classes('w-full gap-2')

        def render_for_selected_decision() -> None:
            adapter_container.clear()
            decision_id = int(selected_decision.value)
            with adapter_container:
                with ui.row().classes('gap-2'):
                    ui.button('Open Decision', on_click=lambda did=decision_id: ui.navigate.to(f'/decisions/{did}')).props('outline')
                    ui.button('Add Outcome', on_click=lambda did=decision_id: ui.navigate.to(f'/decisions/{did}/outcomes/new')).props('outline')
                render_adapter_list(
                    engine=ENGINE,
                    decision_id=decision_id,
                    on_edit=lambda adapter_set_id, did=decision_id: ui.navigate.to(f'/decisions/{did}/adapters/{adapter_set_id}/edit'),
                    on_create=lambda did=decision_id: ui.navigate.to(f'/decisions/{did}/adapters/new'),
                    on_delete=lambda adapter_set_id, did=decision_id: _delete_adapter_set_from_study(
                        study_id,
                        did,
                        adapter_set_id,
                    ),
                )

        selected_decision.on('update:model-value', lambda _: render_for_selected_decision())
        render_for_selected_decision()


def _create_decision_from_study(study_id: int, name: str, description: str, context_ids: list[int]) -> None:
    errors = decision_service.validate_decision_payload(name, description)
    if errors:
        for error in errors:
            ui.notify(error.message, color='negative')
        return
    with Session(ENGINE) as session:
        decision_repo.create_decision(
            session,
            name=name,
            description=description,
            context_ids=context_ids,
        )
    ui.notify('Decision created.', color='positive')
    ui.navigate.to(f'/studies/{study_id}')


def _delete_variable_from_study(study_id: int, variable_id: int) -> None:
    with Session(ENGINE) as session:
        variable_repo.delete_variable(session, variable_id)
    ui.notify('Variable deleted.', color='positive')
    ui.navigate.to(f'/studies/{study_id}')


def _delete_adapter_set_from_study(study_id: int, _decision_id: int, adapter_set_id: int) -> None:
    with Session(ENGINE) as session:
        decision_repo.delete_adapter_set(session, adapter_set_id)
    ui.notify('Adapter set deleted.', color='positive')
    ui.navigate.to(f'/studies/{study_id}')


if __name__ in {'__main__', '__mp_main__'}:
    ui.run(prod_js=False)
else:
    ui.run_with(app, prod_js=False)
