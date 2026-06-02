from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Any

from nicegui import ui
from nicegui.events import UploadEventArguments
from sqlmodel import Session, select

from models import (
    PopulationComparatorKind,
    PopulationComparableValueKind,
    PopulationFeatureDistanceRecord,
    PopulationMatchRunRecord,
    PopulationPersonMatchRecord,
    PopulationPersonRecord,
    PopulationQuestionRecord,
    PopulationTransformKind,
)
from repositories import population_matching_repo, population_repo
from services import (
    population_import_service,
    population_matching_service,
    population_serialization_service,
    population_xlsx_serialization_service,
)
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

    @ui.page('/population/workspaces')
    def population_workspaces() -> None:
        with page_shell(title='Population Workspaces', breadcrumb_path='/population/workspaces', max_width_class='max-w-6xl'):
            _render_workspaces(engine)

    @ui.page('/population/workspaces/{workspace_id}/mappings')
    def population_workspace_mappings(workspace_id: int) -> None:
        with Session(engine) as session:
            workspace = population_matching_repo.get_workspace(session, workspace_id)
        label = workspace.name if workspace else f'#{workspace_id}'
        with page_shell(
            title='Population Mappings',
            breadcrumb_path=f'/population/workspaces/{workspace_id}/mappings',
            max_width_class='max-w-6xl',
            breadcrumb_items=[('Home', '/'), ('Population Workspaces', '/population/workspaces'), (label, None)],
        ):
            if workspace is None:
                ui.label('Population workspace not found.')
                return
            _render_workspace_mappings(engine, workspace_id)

    @ui.page('/population/workspaces/{workspace_id}/matching')
    def population_workspace_matching(workspace_id: int) -> None:
        with page_shell(title='Population Matching', breadcrumb_path=f'/population/workspaces/{workspace_id}/matching', max_width_class='max-w-6xl'):
            _render_matching(engine, workspace_id)

    @ui.page('/population/workspaces/{workspace_id}/runs/{run_id}')
    def population_run_detail(workspace_id: int, run_id: int) -> None:
        with page_shell(title='Population Match Run', breadcrumb_path=f'/population/workspaces/{workspace_id}/runs/{run_id}', max_width_class='max-w-6xl'):
            _render_run_detail(engine, workspace_id, run_id)

    @ui.page('/population/workspaces/{workspace_id}/individual-match')
    def population_individual_matching(workspace_id: int) -> None:
        with page_shell(title='Individual Population Match', breadcrumb_path=f'/population/workspaces/{workspace_id}/individual-match', max_width_class='max-w-6xl'):
            _render_individual_matching(engine, workspace_id)

    @ui.page('/population/workspaces/{workspace_id}/estimate')
    def population_estimate(workspace_id: int) -> None:
        with page_shell(title='Population Estimate', breadcrumb_path=f'/population/workspaces/{workspace_id}/estimate', max_width_class='max-w-6xl'):
            _render_estimate_and_validation(engine, workspace_id)

    @ui.page('/population/workspaces/{workspace_id}/notes')
    def population_notes(workspace_id: int) -> None:
        with page_shell(title='Population Notes', breadcrumb_path=f'/population/workspaces/{workspace_id}/notes', max_width_class='max-w-5xl'):
            _render_workspace_notes(engine, workspace_id)


def _render_population_studies(engine) -> None:
    ui.label('Population data').classes('text-h5')
    ui.label('Imported population studies are read-only in this integration.').classes('text-body2 text-grey-7')
    with ui.row().classes('gap-2'):
        ui.link('Browse questions', '/population/questions')
        ui.link('Import XLSX', '/population/import')
        ui.link('Matching workspaces', '/population/workspaces')
        ui.button('Export datasets', on_click=lambda: _open_population_export_dialog(engine)).props('outline')
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


def _open_population_export_dialog(engine) -> None:
    with Session(engine) as session:
        studies = population_repo.list_studies(session)
        counts = {
            int(study.id): (population_repo.count_people(session, int(study.id)), population_repo.count_questions(session, int(study.id)))
            for study in studies
            if study.id is not None
        }
    if not studies:
        ui.notify('No population studies to export.', color='warning')
        return

    selected: dict[int, Any] = {}
    dialog = ui.dialog()
    with dialog, ui.card().classes('w-full max-w-4xl gap-4'):
        ui.label('Export population datasets').classes('text-h6')
        include_people = ui.checkbox('Include people and responses', value=True)
        ui.label('Choose datasets').classes('text-subtitle2')
        with ui.column().classes('w-full gap-1 max-h-96 overflow-auto'):
            for study in studies:
                if study.id is None:
                    continue
                people, questions = counts.get(int(study.id), (0, 0))
                selected[int(study.id)] = ui.checkbox(
                    f'{study.name} ({people} people, {questions} questions)',
                    value=True,
                ).classes('w-full')
        status = ui.label('').classes('text-body2 text-grey-7')

        def export_selected_json() -> None:
            study_ids = [study_id for study_id, checkbox in selected.items() if checkbox.value]
            if not study_ids:
                ui.notify('Select at least one dataset.', color='warning')
                return
            status.set_text('Building export...')
            with Session(engine) as export_session:
                dataset = population_serialization_service.export_population_dataset(
                    export_session,
                    study_ids=study_ids,
                    include_people=bool(include_people.value),
                )
            content = dataset.model_dump_json(indent=2).encode('utf-8')
            filename = _population_export_filename(study_ids, bool(include_people.value))
            ui.download(content, filename=filename, media_type='application/json')
            status.set_text(f'Exported {len(dataset.studies)} studies, {len(dataset.questions)} questions, {len(dataset.people)} people.')

        def export_selected_xlsx() -> None:
            study_ids = [study_id for study_id, checkbox in selected.items() if checkbox.value]
            if len(study_ids) != 1:
                ui.notify('XLSX export requires exactly one selected dataset.', color='warning')
                return
            status.set_text('Building XLSX export...')
            with tempfile.NamedTemporaryFile(delete=False, suffix='.xlsx') as tmp:
                temp_path = Path(tmp.name)
            try:
                with Session(engine) as export_session:
                    dataset = population_xlsx_serialization_service.export_population_xlsx(
                        export_session,
                        study_id=study_ids[0],
                        path=temp_path,
                        include_people=bool(include_people.value),
                    )
                content = temp_path.read_bytes()
            finally:
                temp_path.unlink(missing_ok=True)
            filename = _population_export_filename(study_ids, bool(include_people.value), suffix='xlsx')
            ui.download(
                content,
                filename=filename,
                media_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            )
            status.set_text(f'Exported {len(dataset.questions)} questions and {len(dataset.people)} people to XLSX.')

        with ui.row().classes('w-full justify-end gap-2'):
            ui.button('Cancel', on_click=dialog.close).props('flat')
            ui.button('Download JSON', on_click=export_selected_json)
            ui.button('Download XLSX', on_click=export_selected_xlsx).props('outline')
    dialog.open()


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
        ui.link('Workspaces', '/population/workspaces')
    render_results()


def _render_workbook_import(engine) -> None:
    ui.label('Import XLSX').classes('text-h5')
    ui.label(
        'Strict workbooks use study, questions, options, and responses sheets. Legacy data workbooks are still supported.'
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
            if population_xlsx_serialization_service.is_strict_population_xlsx(temp_path):
                dataset = population_xlsx_serialization_service.read_population_xlsx(temp_path, source_file_path=filename)
                _open_strict_import_preview_dialog(engine, filename, dataset, status)
                return
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
        ui.link('Matching workspaces', '/population/workspaces')


def _open_strict_import_preview_dialog(engine, filename: str, dataset, status_label) -> None:
    study = dataset.studies[0]
    people_count = len(dataset.people)
    response_count = sum(len(person.responses) for person in dataset.people)
    dialog = ui.dialog()
    with dialog, ui.card().classes('w-full max-w-2xl gap-4'):
        ui.label('Import strict population workbook').classes('text-h6')
        ui.label(filename).classes('text-body2 text-grey-7')
        with ui.column().classes('w-full gap-1'):
            ui.label(f'Study: {study.name} ({study.id})')
            ui.label(f'Questions: {len(dataset.questions)}')
            ui.label(f'People: {people_count}')
            ui.label(f'Responses: {response_count}')
            ui.label('Existing studies, questions, and people with the same external IDs will be skipped.').classes(
                'text-caption text-grey-7'
            )
        preview_status = ui.label('').classes('text-body2 text-grey-7')

        def confirm_import() -> None:
            preview_status.set_text('Importing...')
            try:
                with Session(engine) as session:
                    result = population_serialization_service.import_population_dataset(session, dataset, skip_existing=True)
                    session.commit()
            except Exception as exc:
                preview_status.set_text(f'Import failed: {exc}')
                return
            status_label.set_text(
                f'Imported {filename}: {result.studies_created} studies, {result.questions_created} questions, '
                f'{result.people_created} people, {result.responses_created} responses. '
                f'Skipped {result.studies_skipped + result.questions_skipped + result.people_skipped} existing objects.'
            )
            ui.notify('Strict population workbook imported.', color='positive')
            dialog.close()

        with ui.row().classes('w-full justify-end gap-2'):
            ui.button('Cancel', on_click=dialog.close).props('flat')
            ui.button('Import', on_click=confirm_import, color='primary')
    dialog.open()


def _render_workspaces(engine) -> None:
    ui.label('Matching workspaces').classes('text-h5')
    ui.label('Create a workspace for a source and target population study.').classes('text-body2 text-grey-7')
    with Session(engine) as session:
        studies = population_repo.list_studies(session)
        workspaces = population_matching_repo.list_workspaces(session)
        study_names = {int(study.id): study.name for study in studies if study.id is not None}
        workspace_studies = {
            int(workspace.id): population_matching_repo.list_workspace_studies(session, int(workspace.id))
            for workspace in workspaces
            if workspace.id is not None
        }
    study_options = {int(study.id): study.name for study in studies if study.id is not None}
    name_input = ui.input('Workspace name').classes('w-full')
    description_input = ui.textarea('Description (optional)').classes('w-full')
    source_select = ui.select(study_options, label='Source study').classes('w-full')
    target_select = ui.select(study_options, label='Target study').classes('w-full')

    def create_workspace() -> None:
        name = str(name_input.value or '').strip()
        source_id = int(source_select.value) if source_select.value is not None else None
        target_id = int(target_select.value) if target_select.value is not None else None
        if not name or source_id is None or target_id is None:
            ui.notify('Workspace name, source study, and target study are required.', color='negative')
            return
        if source_id == target_id:
            ui.notify('Choose two different population studies.', color='negative')
            return
        with Session(engine) as session:
            workspace = population_matching_repo.create_workspace(
                session,
                name=name,
                description=str(description_input.value or '').strip() or None,
                source_study_id=source_id,
                target_study_id=target_id,
            )
        ui.navigate.to(f'/population/workspaces/{int(workspace.id)}/mappings')

    ui.button('Create workspace', on_click=create_workspace, color='primary').props('outline')
    ui.separator()
    if not workspaces:
        ui.label('No matching workspaces yet.')
        return
    for workspace in workspaces:
        names = [study_names.get(link.study_id, f'#{link.study_id}') for link in workspace_studies.get(int(workspace.id), [])]
        with ui.row().classes('w-full items-center justify-between border rounded p-2'):
            with ui.column().classes('gap-0'):
                ui.label(workspace.name)
                ui.label(' <-> '.join(names) if names else 'No studies linked').classes('text-caption text-grey-7')
            ui.button('Mappings', on_click=lambda wid=workspace.id: ui.navigate.to(f'/population/workspaces/{int(wid)}/mappings')).props('flat')


def _render_workspace_mappings(engine, workspace_id: int) -> None:
    with Session(engine) as session:
        workspace = population_matching_repo.get_workspace(session, workspace_id)
        study_links = population_matching_repo.list_workspace_studies(session, workspace_id)
        studies = {int(study.id): study for study in population_repo.list_studies(session) if study.id is not None}
        questions_by_study = {link.study_id: population_repo.list_questions(session, study_id=link.study_id) for link in study_links}
    if workspace is None or len(study_links) != 2:
        ui.label('Workspace requires exactly two linked studies.')
        return
    left_id, right_id = [link.study_id for link in study_links]
    left_name = studies.get(left_id).name if studies.get(left_id) else f'#{left_id}'
    right_name = studies.get(right_id).name if studies.get(right_id) else f'#{right_id}'
    ui.label(workspace.name).classes('text-h5')
    ui.label(f'{left_name} <-> {right_name}').classes('text-body2 text-grey-7')
    with ui.row().classes('gap-2'):
        ui.link('Workspaces', '/population/workspaces')
        ui.link('Matching', f'/population/workspaces/{workspace_id}/matching')
    ui.separator()
    ui.label('Mappings').classes('text-h6')
    mapping_list = ui.column().classes('w-full gap-2')

    def render_mapping_list() -> None:
        mapping_list.clear()
        with Session(engine) as session:
            mappings = population_matching_repo.list_mappings(session, workspace_id)
            inputs = {
                int(mapping.id): population_matching_repo.list_mapping_inputs(session, int(mapping.id))
                for mapping in mappings
                if mapping.id is not None
            }
            question_names = {
                int(question.id): question.wording
                for question in population_repo.list_questions(session)
                if question.id is not None
            }
        with mapping_list:
            if not mappings:
                ui.label('No mappings yet.')
                return
            for mapping in mappings:
                with ui.column().classes('w-full gap-1 border rounded p-2'):
                    with ui.row().classes('w-full items-center justify-between'):
                        ui.label(f'{mapping.name} [{mapping.status.value}]').classes('text-subtitle2')
                        if mapping.status.value != 'disabled':
                            ui.button(
                                'Disable',
                                on_click=lambda mid=mapping.id: _disable_mapping_and_refresh(engine, int(mid), render_mapping_list),
                            ).props('flat')
                    ui.label(f'weight={mapping.weight} | output={mapping.output_kind.value}').classes('text-caption text-grey-7')
                    for side in ('left', 'right'):
                        values = [
                            f'{item.alias}: {question_names.get(item.question_id, item.question_id)}'
                            for item in inputs.get(int(mapping.id), [])
                            if item.side == side
                        ]
                        ui.label(f'{side}: {"; ".join(values) or "-"}').classes('text-body2 break-words')

    render_mapping_list()
    ui.separator()
    _render_mapping_form(engine, workspace_id, left_id, right_id, left_name, right_name, questions_by_study)


def _render_mapping_form(engine, workspace_id: int, left_id: int, right_id: int, left_name: str, right_name: str, questions_by_study) -> None:
    ui.label('Add mapping').classes('text-h6')
    name_input = ui.input('Mapping name').classes('w-full')
    description_input = ui.textarea('Description (optional)').classes('w-full')
    notes_input = ui.textarea('Notes (optional)').classes('w-full')
    left_questions = ui.select(_question_options(questions_by_study.get(left_id, [])), label=f'{left_name} inputs', multiple=True).classes('w-full')
    right_questions = ui.select(_question_options(questions_by_study.get(right_id, [])), label=f'{right_name} inputs', multiple=True).classes('w-full')
    left_kind = ui.select({kind.value: kind.value for kind in PopulationTransformKind}, value='identity', label='Left transform').classes('w-full')
    right_kind = ui.select({kind.value: kind.value for kind in PopulationTransformKind}, value='identity', label='Right transform').classes('w-full')
    comparator_kind = ui.select({kind.value: kind.value for kind in PopulationComparatorKind}, value='exact_match', label='Comparator').classes('w-full')
    output_kind = ui.select({kind.value: kind.value for kind in PopulationComparableValueKind}, value='number', label='Output kind').classes('w-full')
    weight_input = ui.number('Weight', value=1, min=0).classes('w-full')
    left_params = ui.textarea('Left transform parameters JSON', value='{}').classes('w-full')
    right_params = ui.textarea('Right transform parameters JSON', value='{}').classes('w-full')
    comparator_params = ui.textarea('Comparator parameters JSON', value='{}').classes('w-full')

    def create_mapping() -> None:
        selected_left = [int(value) for value in (left_questions.value or [])]
        selected_right = [int(value) for value in (right_questions.value or [])]
        if not selected_left or not selected_right:
            ui.notify('Choose at least one input question from each study.', color='negative')
            return
        try:
            left_json = _json_object(str(left_params.value or '{}'), 'Left transform parameters')
            right_json = _json_object(str(right_params.value or '{}'), 'Right transform parameters')
            comparator_json = _json_object(str(comparator_params.value or '{}'), 'Comparator parameters')
        except ValueError as exc:
            ui.notify(str(exc), color='negative')
            return
        left_inputs = _mapping_inputs(selected_left, questions_by_study.get(left_id, []), 'left')
        right_inputs = _mapping_inputs(selected_right, questions_by_study.get(right_id, []), 'right')
        with Session(engine) as session:
            population_matching_repo.create_mapping(
                session,
                workspace_id=workspace_id,
                name=str(name_input.value or '').strip() or 'Mapping',
                description=str(description_input.value or '').strip() or None,
                notes=str(notes_input.value or '').strip() or None,
                left_study_id=left_id,
                right_study_id=right_id,
                left_inputs=left_inputs,
                right_inputs=right_inputs,
                left_transform={'kind': str(left_kind.value), 'input_aliases': [item['alias'] for item in left_inputs], 'parameters': left_json},
                right_transform={'kind': str(right_kind.value), 'input_aliases': [item['alias'] for item in right_inputs], 'parameters': right_json},
                comparator={'kind': str(comparator_kind.value), 'parameters': comparator_json},
                output_kind=PopulationComparableValueKind(str(output_kind.value)),
                weight=float(weight_input.value or 1),
            )
        ui.notify('Mapping saved.', color='positive')
        ui.navigate.to(f'/population/workspaces/{workspace_id}/mappings')

    ui.button('Save mapping', on_click=create_mapping, color='primary').props('outline')


def _render_matching(engine, workspace_id: int) -> None:
    workspace, defaults, study_names = _workspace_context(engine, workspace_id)
    if workspace is None or defaults is None or defaults.source_study_id is None or defaults.target_study_id is None:
        ui.label('Workspace needs source and target matching defaults.')
        return
    _render_workspace_links(workspace_id, workspace.name)
    ui.label('Batch weighted k-NN').classes('text-h5')
    source_options = _workspace_study_options(engine, workspace_id)
    source_select = ui.select(source_options, value=defaults.source_study_id, label='Source study').classes('w-full')
    target_select = ui.select(source_options, value=defaults.target_study_id, label='Target study').classes('w-full')
    k_input = ui.number('k nearest neighbors', value=defaults.k, min=1, max=50).classes('w-full')
    limit_input = ui.number('Source-person limit', value=25, min=1).classes('w-full')
    status = ui.label('Batch runs persist full match details.').classes('text-body2 text-grey-7')

    def run_matching() -> None:
        source_id = int(source_select.value) if source_select.value is not None else None
        target_id = int(target_select.value) if target_select.value is not None else None
        if source_id is None or target_id is None or source_id == target_id:
            ui.notify('Choose two different source and target studies.', color='negative')
            return
        try:
            with Session(engine) as session:
                population_matching_repo.update_matching_defaults(
                    session,
                    workspace_id,
                    source_study_id=source_id,
                    target_study_id=target_id,
                    k=int(k_input.value or 1),
                )
                result = population_matching_service.run_weighted_knn(
                    session,
                    workspace_id=workspace_id,
                    source_limit=int(limit_input.value or 25),
                )
        except Exception as exc:
            status.set_text(f'Matching failed: {exc}')
            return
        ui.navigate.to(f'/population/workspaces/{workspace_id}/runs/{int(result.run.id)}')

    ui.button('Run matching', on_click=run_matching, color='primary').props('outline')
    ui.separator()
    ui.label('Saved runs').classes('text-h6')
    with Session(engine) as session:
        runs = list(
            session.exec(
                select(PopulationMatchRunRecord)
                .where(PopulationMatchRunRecord.workspace_id == workspace_id)
                .order_by(PopulationMatchRunRecord.created_at.desc(), PopulationMatchRunRecord.id.desc())
            )
        )
    if not runs:
        ui.label('No batch runs saved yet.')
        return
    for run in runs:
        source_name = study_names.get(run.source_study_id, f'#{run.source_study_id}')
        target_name = study_names.get(run.target_study_id, f'#{run.target_study_id}')
        with ui.row().classes('w-full items-center justify-between border rounded p-2'):
            with ui.column().classes('gap-0'):
                ui.label(run.external_id)
                ui.label(f'{source_name} -> {target_name} | k={run.k} | matches={run.match_count}').classes('text-caption text-grey-7')
            ui.button('Open', on_click=lambda rid=run.id: ui.navigate.to(f'/population/workspaces/{workspace_id}/runs/{int(rid)}')).props('flat')


def _render_run_detail(engine, workspace_id: int, run_id: int) -> None:
    with Session(engine) as session:
        run = session.get(PopulationMatchRunRecord, run_id)
        workspace = population_matching_repo.get_workspace(session, workspace_id)
        match_rows = list(
            session.exec(
                select(PopulationPersonMatchRecord)
                .where(PopulationPersonMatchRecord.run_id == run_id)
                .order_by(PopulationPersonMatchRecord.source_person_id, PopulationPersonMatchRecord.rank)
            )
        )
        people = {
            int(person.id): person.external_id
            for person in session.exec(select(PopulationPersonRecord))
            if person.id is not None
        }
        feature_rows = {
            int(match.id): list(
                session.exec(
                    select(PopulationFeatureDistanceRecord)
                    .where(PopulationFeatureDistanceRecord.person_match_id == match.id)
                    .order_by(PopulationFeatureDistanceRecord.id)
                )
            )
            for match in match_rows
            if match.id is not None
        }
    if run is None or workspace is None or run.workspace_id != workspace_id:
        ui.label('Match run not found for this workspace.')
        return
    _render_workspace_links(workspace_id, workspace.name)
    ui.label(run.external_id).classes('text-h5')
    ui.label(
        f'{run.match_count} matches | {run.source_people_evaluated} source people | '
        f'average distance={run.average_distance if run.average_distance is not None else "-"}'
    ).classes('text-body2 text-grey-7')
    for match in match_rows:
        with ui.expansion(
            f'{people.get(match.source_person_id, match.source_person_id)} -> '
            f'{people.get(match.target_person_id, match.target_person_id)} | distance={match.distance:.3f}',
        ).classes('w-full border rounded'):
            ui.label(f'rank={match.rank} similarity={match.similarity:.3f} missing features={match.missing_features_count}').classes('text-body2')
            for feature in feature_rows.get(int(match.id), []):
                ui.label(
                    f'{feature.mapping_name}: distance={feature.distance if feature.distance is not None else "-"} '
                    f'weight={feature.weight} missing={feature.missing}'
                ).classes('text-body2')


def _render_individual_matching(engine, workspace_id: int) -> None:
    workspace, defaults, _ = _workspace_context(engine, workspace_id)
    if workspace is None or defaults is None or defaults.source_study_id is None or defaults.target_study_id is None:
        ui.label('Workspace needs matching defaults.')
        return
    _render_workspace_links(workspace_id, workspace.name)
    ui.label('Live individual match').classes('text-h5')
    person_options = _person_options(engine, defaults.source_study_id)
    person_select = ui.select(person_options, label='Source person').classes('w-full')
    k_input = ui.number('k nearest neighbors', value=defaults.k, min=1, max=50).classes('w-full')
    results = ui.column().classes('w-full gap-2')

    def find_matches() -> None:
        results.clear()
        if person_select.value is None:
            ui.notify('Choose a source person.', color='negative')
            return
        try:
            with Session(engine) as session:
                matches = population_matching_service.find_nearest_matches(
                    session,
                    workspace_id=workspace_id,
                    source_person_id=int(person_select.value),
                    source_study_id=defaults.source_study_id,
                    target_study_id=defaults.target_study_id,
                    k=int(k_input.value or 1),
                )
        except Exception as exc:
            ui.notify(f'Live matching failed: {exc}', color='negative')
            return
        with results:
            ui.label(f'{len(matches)} live matches').classes('text-subtitle2')
            _render_live_matches(matches)

    ui.button('Find matches', on_click=find_matches, color='primary').props('outline')


def _render_estimate_and_validation(engine, workspace_id: int) -> None:
    workspace, defaults, _ = _workspace_context(engine, workspace_id)
    if workspace is None or defaults is None or defaults.source_study_id is None or defaults.target_study_id is None:
        ui.label('Workspace needs matching defaults.')
        return
    _render_workspace_links(workspace_id, workspace.name)
    ui.label('Live estimate').classes('text-h5')
    person_select = ui.select(_person_options(engine, defaults.source_study_id), label='Source person').classes('w-full')
    question_select = ui.select(_study_question_options(engine, defaults.target_study_id), label='Target question').classes('w-full')
    k_input = ui.number('k nearest neighbors', value=defaults.k, min=1, max=50).classes('w-full')
    estimate_results = ui.column().classes('w-full gap-2')

    def estimate() -> None:
        estimate_results.clear()
        if person_select.value is None or question_select.value is None:
            ui.notify('Choose a source person and target question.', color='negative')
            return
        try:
            with Session(engine) as session:
                matches = population_matching_service.find_nearest_matches(
                    session,
                    workspace_id=workspace_id,
                    source_person_id=int(person_select.value),
                    source_study_id=defaults.source_study_id,
                    target_study_id=defaults.target_study_id,
                    k=int(k_input.value or 1),
                )
                result = population_matching_service.estimate_from_neighbors(
                    session,
                    matches=matches,
                    target_question_id=int(question_select.value),
                )
        except Exception as exc:
            ui.notify(f'Estimation failed: {exc}', color='negative')
            return
        with estimate_results:
            ui.label(f'Estimate: {_display_value(result.get("estimate"))}').classes('text-subtitle2')
            ui.label(f'Method: {result.get("method")}').classes('text-body2 text-grey-7')
            _render_live_matches(matches)

    ui.button('Estimate from neighbors', on_click=estimate, color='primary').props('outline')
    ui.separator()
    _render_validation(engine, workspace_id, defaults.source_study_id, defaults.target_study_id, defaults.k)


def _render_validation(engine, workspace_id: int, source_study_id: int, target_study_id: int, default_k: int) -> None:
    with Session(engine) as session:
        one_to_one = {
            mapping.id: mapping.name
            for mapping in population_matching_service.active_mappings(session, workspace_id)
            if len(mapping.left_inputs) == 1 and len(mapping.right_inputs) == 1
        }
    ui.label('Holdout validation').classes('text-h5')
    mapping_select = ui.select(one_to_one, label='One-to-one mapping').classes('w-full')
    person_select = ui.select(_person_options(engine, source_study_id), label='Person (for person validation)').classes('w-full')
    k_input = ui.number('Validation k', value=default_k, min=1, max=50).classes('w-full')
    results = ui.column().classes('w-full gap-2')

    def validate_person() -> None:
        results.clear()
        if mapping_select.value is None or person_select.value is None:
            ui.notify('Choose a mapping and person.', color='negative')
            return
        with Session(engine) as session:
            result = population_matching_service.validate_mapping_for_person(
                session,
                workspace_id=workspace_id,
                source_person_id=int(person_select.value),
                source_study_id=source_study_id,
                target_study_id=target_study_id,
                mapping_id=int(mapping_select.value),
                k=int(k_input.value or 1),
            )
        with results:
            if result is None:
                ui.label('No validation case for that person.')
                return
            ui.label(f'Comparison: {result["comparison"]}').classes('text-body2')
            _render_live_matches(result['matches'])

    def validate_population() -> None:
        results.clear()
        if mapping_select.value is None:
            ui.notify('Choose a mapping.', color='negative')
            return
        with Session(engine) as session:
            result = population_matching_service.validate_mapping_population(
                session,
                workspace_id=workspace_id,
                source_study_id=source_study_id,
                target_study_id=target_study_id,
                mapping_id=int(mapping_select.value),
                k=int(k_input.value or 1),
            )
        with results:
            ui.label(f'Summary: {result["summary"]}').classes('text-body2')

    with ui.row().classes('gap-2'):
        ui.button('Validate person', on_click=validate_person).props('outline')
        ui.button('Validate population', on_click=validate_population).props('outline')


def _render_workspace_notes(engine, workspace_id: int) -> None:
    workspace, _, _ = _workspace_context(engine, workspace_id)
    if workspace is None:
        ui.label('Workspace not found.')
        return
    _render_workspace_links(workspace_id, workspace.name)
    ui.label('Workspace notes').classes('text-h5')
    note_input = ui.textarea('Note').classes('w-full')
    tag_input = ui.input('Tags, comma separated').classes('w-full')
    notes_container = ui.column().classes('w-full gap-2')

    def render_notes() -> None:
        notes_container.clear()
        with Session(engine) as session:
            notes = population_matching_repo.list_notes(session, workspace_id)
            tags = {int(note.id): population_matching_repo.list_note_tags(session, int(note.id)) for note in notes if note.id is not None}
        with notes_container:
            if not notes:
                ui.label('No notes yet.')
            for note in notes:
                with ui.column().classes('w-full gap-1 border rounded p-2'):
                    ui.label(note.text).classes('break-words')
                    ui.label(', '.join(tags.get(int(note.id), [])) or 'no tags').classes('text-caption text-grey-7')

    def add_note() -> None:
        text = str(note_input.value or '').strip()
        if not text:
            ui.notify('Write a note first.', color='negative')
            return
        with Session(engine) as session:
            population_matching_repo.add_note(
                session,
                workspace_id,
                text,
                tags=[tag.strip() for tag in str(tag_input.value or '').split(',')],
            )
        note_input.value = ''
        tag_input.value = ''
        render_notes()

    ui.button('Add note', on_click=add_note, color='primary').props('outline')
    render_notes()


def _source_label(source_file: str, source_sheet: str | None) -> str:
    return f'{source_file} | {source_sheet}' if source_sheet else source_file


def _population_export_filename(study_ids: list[int], include_people: bool, suffix: str = 'json') -> str:
    scope = 'full' if include_people else 'questions'
    if len(study_ids) == 1:
        return f'population_export_study_{study_ids[0]}_{scope}.{suffix}'
    return f'population_export_{len(study_ids)}_studies_{scope}.{suffix}'


def _value_label(value_json: str) -> str:
    value = population_repo.json_load(value_json, None)
    return '-' if value is None else str(value)


def _question_options(questions) -> dict[int, str]:
    return {
        int(question.id): f'{question.short_name or question.wording} [{question.kind.value}]'
        for question in questions
        if question.id is not None
    }


def _mapping_inputs(question_ids: list[int], questions, side: str) -> list[dict[str, object]]:
    names = {int(question.id): question.short_name or question.wording for question in questions if question.id is not None}
    return [
        {
            'question_id': question_id,
            'alias': f'{side}_{index}_{_alias_text(names.get(question_id, str(question_id)))}',
            'required': True,
        }
        for index, question_id in enumerate(question_ids, start=1)
    ]


def _alias_text(value: str) -> str:
    text = ''.join(char.lower() if char.isalnum() else '_' for char in value)
    return '_'.join(part for part in text.split('_') if part)[:32] or 'value'


def _json_object(value: str, label: str) -> dict[str, object]:
    try:
        parsed = json.loads(value or '{}')
    except json.JSONDecodeError as exc:
        raise ValueError(f'{label} must be valid JSON: {exc}') from exc
    if not isinstance(parsed, dict):
        raise ValueError(f'{label} must be a JSON object.')
    return parsed


def _disable_mapping_and_refresh(engine, mapping_id: int, refresh) -> None:
    with Session(engine) as session:
        population_matching_repo.disable_mapping(session, mapping_id)
    ui.notify('Mapping disabled.', color='positive')
    refresh()


def _workspace_context(engine, workspace_id: int):
    with Session(engine) as session:
        workspace = population_matching_repo.get_workspace(session, workspace_id)
        defaults = population_matching_repo.get_matching_defaults(session, workspace_id)
        studies = {int(study.id): study.name for study in population_repo.list_studies(session) if study.id is not None}
    return workspace, defaults, studies


def _workspace_study_options(engine, workspace_id: int) -> dict[int, str]:
    with Session(engine) as session:
        study_ids = [link.study_id for link in population_matching_repo.list_workspace_studies(session, workspace_id)]
        studies = {int(study.id): study.name for study in population_repo.list_studies(session) if study.id is not None}
    return {study_id: studies.get(study_id, f'#{study_id}') for study_id in study_ids}


def _render_workspace_links(workspace_id: int, workspace_name: str) -> None:
    ui.label(workspace_name).classes('text-h5')
    with ui.row().classes('gap-2'):
        ui.link('Workspaces', '/population/workspaces')
        ui.link('Mappings', f'/population/workspaces/{workspace_id}/mappings')
        ui.link('Batch matching', f'/population/workspaces/{workspace_id}/matching')
        ui.link('Individual match', f'/population/workspaces/{workspace_id}/individual-match')
        ui.link('Estimate / validate', f'/population/workspaces/{workspace_id}/estimate')
        ui.link('Notes', f'/population/workspaces/{workspace_id}/notes')
    ui.separator()


def _person_options(engine, study_id: int, limit: int = 500) -> dict[int, str]:
    with Session(engine) as session:
        people = list(
            session.exec(
                select(PopulationPersonRecord)
                .where(PopulationPersonRecord.study_id == study_id)
                .order_by(PopulationPersonRecord.id)
                .limit(limit)
            )
        )
    return {int(person.id): _person_label(person) for person in people if person.id is not None}


def _study_question_options(engine, study_id: int, limit: int = 500) -> dict[int, str]:
    with Session(engine) as session:
        questions = list(
            session.exec(
                select(PopulationQuestionRecord)
                .where(PopulationQuestionRecord.study_id == study_id)
                .order_by(PopulationQuestionRecord.wording, PopulationQuestionRecord.id)
                .limit(limit)
            )
        )
    return {int(question.id): _question_label(question) for question in questions if question.id is not None}


def _person_label(person: PopulationPersonRecord) -> str:
    if person.source_person_id and person.source_person_id != person.external_id:
        return f'{person.source_person_id} ({person.external_id})'
    return person.external_id


def _question_label(question: PopulationQuestionRecord) -> str:
    name = question.short_name or question.wording
    return f'{_truncate(name, 120)} [{question.kind.value}]'


def _truncate(value: str, length: int) -> str:
    text = str(value)
    return text if len(text) <= length else f'{text[: length - 1]}...'


def _display_value(value) -> str:
    if isinstance(value, float):
        return f'{value:.3f}'
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)
    return '-' if value is None else str(value)


def _render_live_matches(matches) -> None:
    if not matches:
        ui.label('No matches found.')
        return
    for match in matches:
        with ui.expansion(
            f'{match.source_person_external_id} -> {match.target_person_external_id} | '
            f'distance={match.distance:.3f} similarity={match.similarity:.3f}'
        ).classes('w-full border rounded'):
            ui.label(
                f'matched features={match.matched_features_count} | missing features={match.missing_features_count}'
            ).classes('text-body2 text-grey-7')
            for feature in match.feature_distances:
                source_value = _display_value(feature.source_value)
                target_value = _display_value(feature.target_value)
                distance = '-' if feature.distance is None else f'{feature.distance:.3f}'
                ui.label(
                    f'{feature.mapping_name}: {source_value} -> {target_value}; distance={distance}; '
                    f'weight={feature.weight}; missing={feature.missing}'
                ).classes('text-body2 break-words')
