from __future__ import annotations

from pathlib import Path
import tempfile
from nicegui import app, ui
from nicegui.events import UploadEventArguments
from sqlmodel import Session

from netlogo_ast.main import (
    model_variable_names,
    parse_model_text,
    replace_procedures_in_model_text,
    summarize_procedures,
    upsert_procedures_in_model_text,
)
from models import (
    AdapterLikelihoodMode,
    ConditionOperator,
    create_netlogo_model,
    list_nl_model_adapters,
    Study,
    VarType,
    create_study,
    get_engine,
    init_db,
    list_netlogo_models,
    list_studies,
    replace_nl_model_adapters,
)
from repositories import decision_repo, population_repo, variable_repo
from services import decision_service, netlogo_export_service, netlogo_population_service, variable_service
from ui.components.confirm_actions import confirm_delete_button
from ui.components.page_shell import page_shell
from ui.pages.contexts_page import register_context_pages
from ui.pages.datasets_page import register_dataset_pages
from ui.pages.decisions_page import register_decision_pages
from ui.pages.population_page import register_population_pages
from ui.pages.variables_page import register_variable_pages
from ui.views.adapter.adapter_list_view import render_adapter_list
from ui.views.decision.decision_form_view import ContextOption, render_decision_form


STUDIES_DIR = Path('studies')
STUDIES_DIR.mkdir(parents=True, exist_ok=True)
MODELS_DIR = Path('models')
MODELS_DIR.mkdir(parents=True, exist_ok=True)
init_db()
ENGINE = get_engine()
register_decision_pages(ENGINE)
register_variable_pages(ENGINE)
register_context_pages(ENGINE)
register_dataset_pages(ENGINE)
register_population_pages(ENGINE)


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


def _safe_destination(directory: Path, filename: str) -> Path:
    base_name = Path(filename).name
    candidate = directory / base_name
    if not candidate.exists():
        return candidate

    stem = candidate.stem
    suffix = candidate.suffix
    index = 1
    while True:
        renamed = directory / f'{stem}_{index}{suffix}'
        if not renamed.exists():
            return renamed
        index += 1


@ui.page('/')
def index() -> None:
    with page_shell(title='Home', breadcrumb_path='/', max_width_class='max-w-3xl'):
        ui.label('Choose a section').classes('text-body1')
        ui.link('Go to studies', '/studies/')
        ui.link('Go to NetLogo models', '/netlogo/models')
        ui.link('Go to NetLogo adapters', '/netlogo/adapters')
        ui.link('Read the NetLogo adapter guide', '/netlogo/adapters/guide')
        ui.link('Go to decisions', '/decisions')
        ui.link('Go to variables', '/variables')
        ui.link('Go to contexts', '/contexts')
        ui.link('Go to datasets', '/datasets')
        ui.link('Go to population data', '/population/studies')


@ui.page('/netlogo/models')
def netlogo_models_page() -> None:
    with page_shell(
        title='NetLogo Models',
        breadcrumb_path='/netlogo/models',
        max_width_class='max-w-5xl',
    ):
        status = ui.label('Upload a `.nlogo`/`.nlogox` model or a plain NetLogo source file.').classes('text-body2')
        model_list_container = ui.column().classes('w-full gap-2')
        results_container = ui.column().classes('w-full gap-2')

        def render_model_list() -> None:
            model_list_container.clear()
            with Session(ENGINE) as session:
                stored_models = list_netlogo_models(session)
            with model_list_container:
                ui.label('Saved models').classes('text-subtitle2')
                if not stored_models:
                    ui.label('No NetLogo models uploaded yet.')
                    return
                for model in stored_models:
                    with ui.row().classes('w-full items-center justify-between border rounded p-2'):
                        ui.label(model.model_name).classes('text-body2')

        def render_results(filename: str, procedures: list[object]) -> None:
            results_container.clear()
            with results_container:
                ui.label(f'{filename}: {len(procedures)} procedures').classes('text-subtitle2')
                if not procedures:
                    ui.label('No procedures found.')
                    return
                with ui.element('div').classes('w-full grid grid-cols-4 gap-3 font-medium text-grey-7 border-b pb-1'):
                    ui.label('Name')
                    ui.label('Asked by')
                    ui.label('Args')
                    ui.label('Variables changed')
                for procedure in procedures:
                    called_by = ', '.join(procedure.called_by) if procedure.called_by else 'observer'
                    args = ', '.join(procedure.args) if procedure.args else '-'
                    variables_changed = ', '.join(procedure.variables_changed) if procedure.variables_changed else '-'
                    with ui.element('div').classes('w-full grid grid-cols-4 gap-3 border rounded p-2'):
                        ui.label(procedure.name).classes('break-words')
                        ui.label(called_by).classes('break-words')
                        ui.label(args).classes('break-words')
                        ui.label(variables_changed).classes('break-words')

        async def handle_upload(event: UploadEventArguments) -> None:
            suffix = Path(event.file.name).suffix.lower()
            if suffix not in {'.nlogo', '.nlogox', '.txt', '.nl', '.netlogo'}:
                status.set_text('Unsupported file type. Use .nlogo, .nlogox, or a plain NetLogo source file.')
                return

            with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
                temp_path = Path(tmp.name)
            await event.file.save(temp_path)

            try:
                model_text = temp_path.read_text(encoding='utf-8')
                program = parse_model_text(model_text)
                procedures = summarize_procedures(program)
                destination = _safe_destination(MODELS_DIR, event.file.name)
                destination.write_bytes(temp_path.read_bytes())
                with Session(ENGINE) as session:
                    create_netlogo_model(session, model_name=destination.name)
            except UnicodeDecodeError:
                status.set_text('Could not read file as UTF-8 text.')
                return
            except Exception as exc:
                status.set_text(f'Parse failed: {exc}')
                return
            finally:
                temp_path.unlink(missing_ok=True)

            status.set_text(f'Parsed {Path(event.file.name).name}.')
            render_model_list()
            render_results(Path(event.file.name).name, procedures)

        ui.upload(on_upload=handle_upload, auto_upload=True).props('accept=.nlogo,.nlogox,.txt,.nl,.netlogo')
        ui.link('Create population package', '/netlogo/population-package')
        render_model_list()


@ui.page('/netlogo/population-package')
def netlogo_population_package_page() -> None:
    with page_shell(
        title='NetLogo Population Package',
        breadcrumb_path='/netlogo/population-package',
        max_width_class='max-w-5xl',
    ):
        status = ui.label(
            'Choose a NetLogo model, a population study, fields, and an agent type. Then download a zip package.'
        ).classes('text-body2')

        with Session(ENGINE) as session:
            models = list_netlogo_models(session)
            studies = population_repo.list_studies(session)

        model_options = {int(model.id): model.model_name for model in models if model.id is not None}
        study_options = {int(study.id): study.name for study in studies if study.id is not None}

        selected_model = ui.select(model_options, label='NetLogo model').classes('w-full')
        selected_study = ui.select(study_options, label='Population dataset').classes('w-full')
        agent_select = ui.select({}, label='Breed or turtles').classes('w-full')
        field_select = ui.select({}, label='Population fields', multiple=True).classes('w-full')

        preview_container = ui.column().classes('w-full gap-1')

        def load_model_text(model_id: int | None) -> tuple[str, str] | None:
            if model_id is None:
                return None
            model_record = next((model for model in models if model.id == model_id), None)
            if model_record is None:
                return None
            model_path = MODELS_DIR / model_record.model_name
            if not model_path.exists():
                raise ValueError(f'Model file not found: {model_record.model_name}')
            return model_record.model_name, model_path.read_text(encoding='utf-8')

        def set_select_options(control, options: dict, value=None) -> None:
            control.options = options
            control.value = value
            control.update()

        def refresh_agents() -> None:
            model_id = int(selected_model.value) if selected_model.value is not None else None
            try:
                loaded = load_model_text(model_id)
                options = netlogo_population_service.breed_options(loaded[1]) if loaded else {}
            except Exception as exc:
                status.set_text(f'Could not inspect model breeds: {exc}')
                options = {}
            set_select_options(agent_select, options, 'turtles' if 'turtles' in options else None)

        def refresh_fields() -> None:
            study_id = int(selected_study.value) if selected_study.value is not None else None
            if study_id is None:
                set_select_options(field_select, {})
                return
            with Session(ENGINE) as session:
                questions = population_repo.list_questions(session, study_id=study_id, limit=2000)
            options = {
                int(question.id): f'{question.short_name or question.wording} [{question.kind.value}]'
                for question in questions
                if question.id is not None
            }
            set_select_options(field_select, options)

        def render_preview() -> None:
            preview_container.clear()
            question_ids = [int(value) for value in (field_select.value or [])]
            if not question_ids:
                return
            with Session(ENGINE) as session:
                questions = {
                    int(question.id): question
                    for question in population_repo.list_questions(session)
                    if question.id in question_ids and question.id is not None
                }
            used: set[str] = set()
            with preview_container:
                ui.label('Field name preview').classes('text-subtitle2')
                for question_id in question_ids:
                    question = questions.get(question_id)
                    if question is None:
                        continue
                    source_name = question.short_name or question.wording
                    base = netlogo_population_service.safe_netlogo_name(source_name)
                    name = base
                    suffix = 2
                    while name in used:
                        name = f'{base}-{suffix}'
                        suffix += 1
                    used.add(name)
                    ui.label(f'{source_name} -> {name}').classes('text-body2 break-words')

        def generate_package() -> None:
            model_id = int(selected_model.value) if selected_model.value is not None else None
            study_id = int(selected_study.value) if selected_study.value is not None else None
            question_ids = [int(value) for value in (field_select.value or [])]
            agent_kind = str(agent_select.value or '').strip()
            if model_id is None or study_id is None or not question_ids or not agent_kind:
                status.set_text('Choose model, population dataset, fields, and agent type.')
                return
            try:
                loaded = load_model_text(model_id)
                if loaded is None:
                    raise ValueError('Model not found.')
                model_filename, model_text = loaded
                with Session(ENGINE) as session:
                    package = netlogo_population_service.build_population_package(
                        session,
                        model_text=model_text,
                        model_filename=model_filename,
                        study_id=study_id,
                        question_ids=question_ids,
                        agent_kind=agent_kind,
                    )
            except Exception as exc:
                status.set_text(f'Package generation failed: {exc}')
                return
            ui.download(package.content, filename=package.filename, media_type='application/zip')
            status.set_text(f'Generated {package.filename} with {package.row_count} population rows.')

        selected_model.on('update:model-value', lambda _: refresh_agents())
        selected_study.on('update:model-value', lambda _: refresh_fields())
        field_select.on('update:model-value', lambda _: render_preview())

        with ui.row().classes('w-full items-center gap-2'):
            ui.button('Generate package', on_click=generate_package, color='primary').props('outline')
            ui.link('Back to NetLogo models', '/netlogo/models')

        refresh_agents()
        refresh_fields()


@ui.page('/netlogo/adapters')
def netlogo_adapters_page() -> None:
    with page_shell(
        title='NetLogo Adapters',
        breadcrumb_path='/netlogo/adapters',
        max_width_class='max-w-5xl',
    ):
        status = ui.label('Choose a model, map decisions to procedures, and download a generated model.').classes('text-body2')

        with Session(ENGINE) as session:
            models = list_netlogo_models(session)
            decisions = decision_repo.list_decisions(session)

        model_options = {
            int(model.id): model.model_name
            for model in models
            if model.id is not None
        }
        decision_options = {
            int(decision.id): decision.name
            for decision in decisions
            if decision.id is not None
        }

        selected_model = ui.select(model_options, label='Model').classes('w-full')
        selected_decisions = ui.select(
            decision_options,
            label='Decisions',
            multiple=True,
        ).classes('w-full')
        mapping_container = ui.column().classes('w-full gap-3')
        existing_container = ui.column().classes('w-full gap-2')
        procedure_selects: dict[int, object] = {}
        procedures_by_name: dict[str, object] = {}

        def render_existing_mappings(model_id: int | None) -> None:
            existing_container.clear()
            if model_id is None:
                return
            with Session(ENGINE) as session:
                mappings = list_nl_model_adapters(session, model_id)
                decision_names = {
                    int(decision.id): decision.name
                    for decision in decision_repo.list_decisions(session)
                    if decision.id is not None
                }
            with existing_container:
                ui.label('Saved mappings').classes('text-subtitle2')
                if not mappings:
                    ui.label('No saved mappings for this model.')
                    return
                for mapping in mappings:
                    decision_name = decision_names.get(mapping.decision_id, f'#{mapping.decision_id}')
                    ui.label(f'{decision_name} -> {mapping.procedure_name}').classes('text-body2')

        def load_procedures(model_id: int | None) -> list[object]:
            if model_id is None:
                return []
            model_record = next((model for model in models if model.id == model_id), None)
            if model_record is None:
                return []
            model_path = MODELS_DIR / model_record.model_name
            if not model_path.exists():
                raise ValueError(f'Model file not found: {model_record.model_name}')
            model_text = model_path.read_text(encoding='utf-8')
            program = parse_model_text(model_text)
            return list(program.procedures)

        def eligible_procedures(model_id: int | None) -> list[object]:
            procedures = load_procedures(model_id)
            return [
                procedure
                for procedure in procedures
                if procedure.is_reporter and [arg.lower() for arg in procedure.args] == ['choices']
            ]

        def render_mapping_selects() -> None:
            nonlocal procedures_by_name
            mapping_container.clear()
            procedure_selects.clear()
            procedures_by_name = {}
            model_id = int(selected_model.value) if selected_model.value is not None else None
            selected_ids = [int(value) for value in (selected_decisions.value or [])]
            if model_id is None or not selected_ids:
                render_existing_mappings(model_id)
                return

            try:
                procedures = eligible_procedures(model_id)
            except Exception as exc:
                status.set_text(f'Could not load procedures: {exc}')
                render_existing_mappings(model_id)
                return

            with mapping_container:
                ui.label('Procedure mappings').classes('text-subtitle2')
                if not procedures:
                    ui.label('No reporter procedures with one `choices` argument are eligible.').classes(
                        'text-body2 text-grey-7'
                    )
                    render_existing_mappings(model_id)
                    return
                procedures_by_name = {procedure.name: procedure for procedure in procedures}
                procedure_options = {
                    procedure.name: _procedure_option_label(procedure)
                    for procedure in procedures
                }
                for decision_id in selected_ids:
                    decision_name = decision_options.get(decision_id, f'#{decision_id}')
                    procedure_selects[decision_id] = ui.select(
                        procedure_options,
                        label=decision_name,
                    ).classes('w-full')
            render_existing_mappings(model_id)

        def handle_generate() -> None:
            if selected_model.value is None:
                status.set_text('Choose a model first.')
                return

            model_id = int(selected_model.value)
            selected_ids = [int(value) for value in (selected_decisions.value or [])]
            if not selected_ids:
                status.set_text('Choose at least one decision.')
                return

            mappings: list[tuple[int, str]] = []
            used_procedures: set[str] = set()
            for decision_id in selected_ids:
                control = procedure_selects.get(decision_id)
                procedure_name = str(control.value or '').strip() if control is not None else ''
                if not procedure_name:
                    status.set_text('Each selected decision must be mapped to a procedure.')
                    return
                if procedure_name in used_procedures:
                    status.set_text('Each procedure can only be mapped once per generated model.')
                    return
                used_procedures.add(procedure_name)
                mappings.append((decision_id, procedure_name))

            model_record = next((model for model in models if model.id == model_id), None)
            if model_record is None:
                status.set_text('Selected model was not found.')
                return

            model_path = MODELS_DIR / model_record.model_name
            if not model_path.exists():
                status.set_text(f'Model file not found: {model_record.model_name}')
                return

            try:
                original_text = model_path.read_text(encoding='utf-8')
                model_variables = model_variable_names(original_text)
                replacements: dict[str, str] = {}
                with Session(ENGINE) as session:
                    for decision_id, procedure_name in mappings:
                        mapped_procedure = procedures_by_name.get(procedure_name)
                        if mapped_procedure is None:
                            raise ValueError(f'Procedure metadata missing for {procedure_name}.')
                        missing_variables = sorted(
                            set(netlogo_export_service.referenced_variable_names(session, decision_id))
                            - model_variables
                        )
                        if missing_variables:
                            missing_text = ', '.join(missing_variables)
                            raise ValueError(
                                f'Model variables required by {procedure_name} are not present: {missing_text}.'
                            )
                        replacements[procedure_name] = netlogo_export_service.export_decision_reporter_named(
                            session,
                            decision_id,
                            reporter_name=procedure_name,
                            include_helpers=False,
                            reporter_args=list(mapped_procedure.args),
                            outcome_rows_expr='choices',
                        )

                generated_text = replace_procedures_in_model_text(original_text, replacements)
                helper_program = netlogo_export_service.export_helper_library()
                helper_blocks = _split_netlogo_procedures(helper_program)
                generated_text = upsert_procedures_in_model_text(generated_text, helper_blocks)
                with Session(ENGINE) as session:
                    replace_nl_model_adapters(session, model_id, mappings)
            except Exception as exc:
                status.set_text(f'Generation failed: {exc}')
                return

            download_name = f'{Path(model_record.model_name).stem}_generated{Path(model_record.model_name).suffix}'
            ui.download(generated_text.encode('utf-8'), filename=download_name, media_type='text/plain')
            status.set_text(f'Generated {download_name}.')
            render_existing_mappings(model_id)

        selected_model.on('update:model-value', lambda _: render_mapping_selects())
        selected_decisions.on('update:model-value', lambda _: render_mapping_selects())
        with ui.row().classes('w-full items-center gap-2'):
            ui.button('Generate and Download', on_click=handle_generate, color='primary').props('outline')
            ui.link('How this works', '/netlogo/adapters/guide')
        render_mapping_selects()


@ui.page('/netlogo/adapters/guide')
def netlogo_adapter_guide_page() -> None:
    with page_shell(
        title='NetLogo Adapter Guide',
        breadcrumb_path='/netlogo/adapters/guide',
        max_width_class='max-w-5xl',
    ):
        ui.label('NetLogo decision injection').classes('text-h5')
        ui.label(
            'This page describes the NetLogo modelling contract for injecting Behavior Manager decisions.'
        ).classes('text-body1')

        _guide_section(
            'What Happens To Procedures',
            [
                'A decision is mapped to one existing procedure in the NetLogo model.',
                'Generation replaces that whole procedure block, from its `to-report` header through its matching `end`.',
                'The original body is not merged with the generated body. Put behaviour that must survive outside the injected procedure.',
                'The replacement is always a reporter. It returns normalized outcome rows for the mapped decision.',
                'The generated model also receives the shared `bm-*` reporter helpers used by injected procedures.',
            ],
        )

        _guide_section(
            'Procedure Requirements',
            [
                'The target must be a named NetLogo procedure that the parser can find in the model code.',
                'The target must be a `to-report` reporter.',
                'The target must have exactly one argument, named `choices`.',
                'Each generated decision must use a different target procedure in the same model.',
            ],
        )

        _guide_section(
            'Choices',
            [
                '`choices` is the initial outcome-row list supplied by the NetLogo model.',
                'It must be rows shaped like `(list (list "outcome-name" probability) ...)`.',
                'The generated reporter starts from those incoming rows rather than creating model choices itself.',
                'The model remains responsible for constructing and passing those rows.',
            ],
        )

        _guide_code(
            'Procedure shape before and after injection',
            '''to-report choose-lunch [choices]
  report choices
end

;; after injection
to-report choose-lunch [choices]
  let __outcomes choices
  if ((reducer = true)) [
    set __outcomes (bm-apply-multiply __outcomes "vegetarian" 1.5)
  ]
  report (bm-normalize __outcomes)
end''',
        )

        _guide_section(
            'Adapter Logic',
            [
                'Adapter-set conditions become NetLogo `if` expressions inside the replacement reporter.',
                'Active adapter effects transform the outcome rows through generated `bm-*` helper calls.',
                'The reporter normalizes rows before it reports them.',
                'If the model already has a helper procedure with the same `bm-*` name, it is replaced with the generated helper.',
            ],
        )

        _guide_section(
            'Variable Assumptions',
            [
                'Injection does not create NetLogo globals, turtle variables, patch variables, or local variables for adapter expressions.',
                'Generation checks that every variable emitted by decision conditions and linear adapter coefficients is present as a code declaration or `.nlogox` widget variable.',
                'Every Behavior Manager variable used by conditions or linear adapter coefficients must already be valid in the scope where the generated reporter runs.',
                'Behavior Manager variable names are sanitized into NetLogo identifiers: spaces and unsupported characters become hyphens, names are lowercased, repeated hyphens collapse, and names starting with a digit get an `r-` prefix.',
                'For example, `Vegetarian Default` is referenced as `vegetarian-default` in generated NetLogo code.',
                'Variable values must have the kind expected by the generated expression: numeric values for linear coefficients and comparable values for predicates.',
            ],
        )

        _guide_section(
            'Model Code',
            [
                'For `.nlogox`, injectable procedures must be in the XML `<model><code>...</code></model>` code element.',
                'For `.nlogo`, injectable procedures must be in the Code tab section before the `@#$#@#$#@` separator.',
                'The model source must be readable as UTF-8 text and the target procedure must parse well enough to appear in the procedure selector.',
            ],
        )

        with ui.row().classes('w-full gap-2'):
            ui.link('Upload models', '/netlogo/models')
            ui.link('Create NetLogo adapters', '/netlogo/adapters')


@ui.page('/netlogo/procedures')
def netlogo_procedures_redirect() -> None:
    ui.navigate.to('/netlogo/models')


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

            destination = _safe_destination(STUDIES_DIR, filename)
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


def _split_netlogo_procedures(code: str) -> dict[str, str]:
    import re

    pattern = re.compile(r'(?ims)^[ \t]*(?:to|to-report)\s+([A-Za-z_][A-Za-z0-9_\-\?\!]*)[\s\S]*?^[ \t]*end[ \t]*$')
    procedures: dict[str, str] = {}
    for match in pattern.finditer(code.strip()):
        procedures[match.group(1)] = match.group(0).strip()
    return procedures


def _procedure_option_label(procedure) -> str:
    args = f' [{" ".join(procedure.args)}]' if procedure.args else ''
    kind = 'to-report' if procedure.is_reporter else 'to'
    return f'{kind} {procedure.name}{args}'


def _guide_section(title: str, items: list[str]) -> None:
    with ui.column().classes('w-full gap-1'):
        ui.label(title).classes('text-h6')
        with ui.column().classes('w-full gap-1 pl-4'):
            for item in items:
                ui.label(f'- {item}').classes('text-body2')


def _guide_code(title: str, code: str) -> None:
    with ui.column().classes('w-full gap-1'):
        ui.label(title).classes('text-h6')
        ui.code(code).classes('w-full')


if __name__ in {'__main__', '__mp_main__'}:
    ui.run(prod_js=False, port=8002)
else:
    ui.run_with(app, prod_js=False)
