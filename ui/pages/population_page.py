from __future__ import annotations

import tempfile
from pathlib import Path

from nicegui import ui
from nicegui.events import UploadEventArguments
from sqlmodel import Session

from repositories import population_repo
from services import population_import_service
from ui.components.page_shell import page_shell


def register_population_pages(engine) -> None:
    @ui.page('/population')
    def population_index() -> None:
        ui.navigate.to('/population/studies')

    @ui.page('/population/studies')
    def population_studies() -> None:
        with page_shell(title='Population Studies', breadcrumb_path='/population/studies', max_width_class='max-w-6xl'):
            _render_population_studies(engine)

    @ui.page('/population/studies/{study_id}')
    def population_study_detail(study_id: int) -> None:
        with Session(engine) as session:
            study = session.get(population_repo.PopulationStudyRecord, study_id)
        label = study.name if study else f'#{study_id}'
        with page_shell(
            title='Population Study',
            breadcrumb_path=f'/population/studies/{study_id}',
            max_width_class='max-w-6xl',
            breadcrumb_items=[('Home', '/'), ('Population Studies', '/population/studies'), (label, None)],
        ):
            if study is None:
                ui.label('Population study not found.')
                return
            _render_study_detail(engine, study_id)

    @ui.page('/population/studies/{study_id}/people/{person_id}')
    def population_person_detail(study_id: int, person_id: int) -> None:
        with Session(engine) as session:
            study = session.get(population_repo.PopulationStudyRecord, study_id)
            person = session.get(population_repo.PopulationPersonRecord, person_id)
        study_label = study.name if study else f'#{study_id}'
        person_label = person.external_id if person else f'#{person_id}'
        with page_shell(
            title='Population Person',
            breadcrumb_path=f'/population/studies/{study_id}/people/{person_id}',
            max_width_class='max-w-6xl',
            breadcrumb_items=[
                ('Home', '/'),
                ('Population Studies', '/population/studies'),
                (study_label, f'/population/studies/{study_id}'),
                (person_label, None),
            ],
        ):
            if study is None or person is None or person.study_id != study_id:
                ui.label('Population person not found for this study.')
                return
            _render_person_detail(engine, person_id)

    @ui.page('/population/questions')
    def population_questions() -> None:
        with page_shell(title='Population Questions', breadcrumb_path='/population/questions', max_width_class='max-w-6xl'):
            _render_question_browser(engine)

    @ui.page('/population/import')
    def population_import() -> None:
        with page_shell(title='Import Population Workbook', breadcrumb_path='/population/import', max_width_class='max-w-5xl'):
            _render_workbook_import(engine)


def _render_population_studies(engine) -> None:
    ui.label('Population data').classes('text-h5')
    ui.label('Imported population studies are read-only in this integration.').classes('text-body2 text-grey-7')
    with ui.row().classes('gap-2'):
        ui.link('Browse questions', '/population/questions')
        ui.link('Import XLSX', '/population/import')
    with Session(engine) as session:
        studies = population_repo.list_studies(session)
        counts = {
            int(study.id): (population_repo.count_people(session, int(study.id)), population_repo.count_questions(session, int(study.id)))
            for study in studies
            if study.id is not None
        }
    ui.separator()
    if not studies:
        ui.label('No population studies imported yet.')
        return
    with ui.element('div').classes('w-full grid grid-cols-[minmax(0,2fr)_7rem_7rem_minmax(0,2fr)_5rem] gap-3 font-medium text-grey-7 border-b pb-1'):
        ui.label('Study')
        ui.label('People')
        ui.label('Questions')
        ui.label('Source')
        ui.label('')
    for study in studies:
        people, questions = counts.get(int(study.id), (0, 0))
        with ui.element('div').classes('w-full grid grid-cols-[minmax(0,2fr)_7rem_7rem_minmax(0,2fr)_5rem] gap-3 border rounded p-2 items-center'):
            ui.label(study.name).classes('break-words')
            ui.label(str(people))
            ui.label(str(questions))
            ui.label(_source_label(study.source_file, study.source_sheet)).classes('break-words text-body2 text-grey-7')
            ui.button('Open', on_click=lambda sid=study.id: ui.navigate.to(f'/population/studies/{int(sid)}')).props('flat')


def _render_study_detail(engine, study_id: int) -> None:
    with Session(engine) as session:
        study = session.get(population_repo.PopulationStudyRecord, study_id)
        people_count = population_repo.count_people(session, study_id)
        question_count = population_repo.count_questions(session, study_id)
        questions = population_repo.list_questions(session, study_id=study_id, limit=20)
        people = population_repo.list_people(session, study_id=study_id, limit=50)
    if study is None:
        return
    ui.label(study.name).classes('text-h5')
    ui.label(_source_label(study.source_file, study.source_sheet)).classes('text-body2 text-grey-7')
    with ui.row().classes('gap-3'):
        ui.label(f'{people_count} people').classes('border rounded px-2 py-1')
        ui.label(f'{question_count} questions').classes('border rounded px-2 py-1')
        ui.link('All questions', '/population/questions')
    ui.separator()
    ui.label('Questions').classes('text-h6')
    if not questions:
        ui.label('No questions for this study.')
    for question in questions:
        with ui.row().classes('w-full items-start justify-between border rounded p-2'):
            with ui.column().classes('gap-0'):
                ui.label(question.wording).classes('break-words')
                ui.label(f'{question.kind.value} | {question.role.value} | {question.external_id}').classes('text-caption text-grey-7 break-all')
    if question_count > len(questions):
        ui.label(f'Showing the first {len(questions)} questions. Use the question browser for filtering.').classes('text-caption text-grey-7')
    ui.separator()
    ui.label('People').classes('text-h6')
    if not people:
        ui.label('No people for this study.')
        return
    for person in people:
        with ui.row().classes('w-full items-center justify-between border rounded p-2'):
            with ui.column().classes('gap-0'):
                ui.label(person.external_id).classes('break-all')
                ui.label(f'source person: {person.source_person_id or "-"}').classes('text-caption text-grey-7')
            ui.button(
                'Responses',
                on_click=lambda pid=person.id: ui.navigate.to(f'/population/studies/{study_id}/people/{int(pid)}'),
            ).props('flat')
    if people_count > len(people):
        ui.label(f'Showing the first {len(people)} people.').classes('text-caption text-grey-7')


def _render_person_detail(engine, person_id: int) -> None:
    with Session(engine) as session:
        person = session.get(population_repo.PopulationPersonRecord, person_id)
        responses = population_repo.list_responses(session, person_id)
        question_ids = {response.question_id for response in responses}
        questions = {
            int(question.id): question
            for question in population_repo.list_questions(session)
            if question.id in question_ids and question.id is not None
        }
        attributes = list(person.attributes) if person else []
        weights = list(person.weights) if person else []
    if person is None:
        return
    ui.label(person.external_id).classes('text-h5 break-all')
    ui.label(f'Source person: {person.source_person_id or "-"}').classes('text-body2 text-grey-7')
    if attributes:
        ui.label('Attributes').classes('text-h6')
        for attribute in attributes:
            ui.label(f'{attribute.name}: {_value_label(attribute.normalized_json)}').classes('text-body2')
    if weights:
        ui.label('Weights').classes('text-h6')
        for weight in weights:
            ui.label(f'{weight.name}: {weight.value}').classes('text-body2')
    ui.separator()
    ui.label(f'Responses ({len(responses)})').classes('text-h6')
    for response in responses:
        question = questions.get(response.question_id)
        with ui.element('div').classes('w-full grid grid-cols-[minmax(0,2fr)_10rem_minmax(0,1fr)] gap-3 border rounded p-2'):
            ui.label(question.wording if question else f'Question #{response.question_id}').classes('break-words')
            ui.label(response.value_kind.value)
            ui.label(_value_label(response.normalized_json)).classes('break-words')


def _render_question_browser(engine) -> None:
    with Session(engine) as session:
        studies = population_repo.list_studies(session)
    study_options = {0: 'All studies'}
    study_options.update({int(study.id): study.name for study in studies if study.id is not None})
    selected_study = ui.select(study_options, value=0, label='Study').classes('w-full')
    search_input = ui.input('Question text').classes('w-full')
    result_container = ui.column().classes('w-full gap-2')

    def render_results() -> None:
        result_container.clear()
        study_id = int(selected_study.value) if selected_study.value else None
        if study_id == 0:
            study_id = None
        with Session(engine) as session:
            questions = population_repo.list_questions(
                session,
                study_id=study_id,
                search=str(search_input.value or '').strip() or None,
                limit=200,
            )
            study_names = {int(study.id): study.name for study in population_repo.list_studies(session) if study.id is not None}
        with result_container:
            ui.label(f'{len(questions)} questions').classes('text-subtitle2')
            for question in questions:
                with ui.column().classes('w-full gap-0 border rounded p-2'):
                    ui.label(question.wording).classes('break-words')
                    ui.label(
                        f'{study_names.get(question.study_id, question.study_id)} | {question.kind.value} | {question.role.value}'
                    ).classes('text-caption text-grey-7')
            if len(questions) == 200:
                ui.label('Showing the first 200 results. Narrow the filter to inspect more.').classes('text-caption text-grey-7')

    with ui.row().classes('gap-2'):
        ui.button('Filter', on_click=render_results).props('outline')
        ui.link('Studies', '/population/studies')
        ui.link('Import XLSX', '/population/import')
    render_results()


def _render_workbook_import(engine) -> None:
    ui.label('Import XLSX').classes('text-h5')
    ui.label(
        'Data workbooks import one study per populated sheet. Filenames containing `question-items` import question catalogs.'
    ).classes('text-body2')
    status = ui.label('Upload a .xlsx workbook.').classes('text-caption text-grey-7')

    async def handle_upload(event: UploadEventArguments) -> None:
        filename = Path(event.file.name).name
        if Path(filename).suffix.lower() != '.xlsx':
            status.set_text('Upload rejected: only .xlsx workbooks are supported here.')
            return
        with tempfile.NamedTemporaryFile(delete=False, suffix='.xlsx') as tmp:
            temp_path = Path(tmp.name)
        await event.file.save(temp_path)
        try:
            content = temp_path.read_bytes()
            with Session(engine) as session:
                result = population_import_service.import_workbook_bytes(session, filename=filename, content=content)
        except Exception as exc:
            status.set_text(f'Import failed: {exc}')
            return
        finally:
            temp_path.unlink(missing_ok=True)
        status.set_text(
            f'Imported {filename}: {result.study_count} studies, {result.question_count} questions, '
            f'{result.person_count} people.'
        )
        ui.notify('Population workbook imported.', color='positive')

    ui.upload(on_upload=handle_upload, auto_upload=True).props('accept=.xlsx')
    with ui.row().classes('gap-2'):
        ui.link('Population studies', '/population/studies')
        ui.link('Question browser', '/population/questions')


def _source_label(source_file: str, source_sheet: str | None) -> str:
    return f'{source_file} | {source_sheet}' if source_sheet else source_file


def _value_label(value_json: str) -> str:
    value = population_repo.json_load(value_json, None)
    return '-' if value is None else str(value)
