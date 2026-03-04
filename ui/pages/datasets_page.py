from __future__ import annotations

import tempfile
from pathlib import Path

from sqlalchemy.exc import IntegrityError
from nicegui import ui
from nicegui.events import UploadEventArguments
from sqlmodel import Session

from models import DatasetFieldType
from repositories import dataset_repo
from services import dataset_import_service, dataset_service
from ui.components.confirm_actions import confirm_delete_button
from ui.components.messages import show_errors
from ui.components.page_shell import page_shell


def register_dataset_pages(engine) -> None:
    @ui.page('/datasets')
    def datasets_index() -> None:
        with page_shell(title='Datasets', breadcrumb_path='/datasets', max_width_class='max-w-5xl'):
            _render_dataset_list(engine)

    @ui.page('/datasets/{dataset_id}')
    def dataset_detail(dataset_id: int) -> None:
        with Session(engine) as session:
            dataset = dataset_repo.get_dataset(session, dataset_id)
        label = dataset.name if dataset else f'#{dataset_id}'
        with page_shell(
            title='Dataset',
            breadcrumb_path=f'/datasets/{dataset_id}',
            max_width_class='max-w-6xl',
            breadcrumb_items=[('Home', '/'), ('Datasets', '/datasets'), (label, None)],
        ):
            if dataset is None:
                ui.label('Dataset not found.')
                ui.button('Back', on_click=lambda: ui.navigate.to('/datasets'))
                return
            _render_dataset_detail(engine, dataset_id)

    @ui.page('/datasets/{dataset_id}/rows/new')
    def datapoint_create(dataset_id: int) -> None:
        with Session(engine) as session:
            dataset = dataset_repo.get_dataset(session, dataset_id)
        label = dataset.name if dataset else f'#{dataset_id}'
        with page_shell(
            title='Create Datapoint',
            breadcrumb_path=f'/datasets/{dataset_id}/rows/new',
            max_width_class='max-w-4xl',
            breadcrumb_items=[('Home', '/'), ('Datasets', '/datasets'), (label, f'/datasets/{dataset_id}'), ('New Row', None)],
        ):
            _render_datapoint_form(engine, dataset_id, datapoint_id=None)

    @ui.page('/datasets/{dataset_id}/rows/{datapoint_id}/edit')
    def datapoint_edit(dataset_id: int, datapoint_id: int) -> None:
        with Session(engine) as session:
            dataset = dataset_repo.get_dataset(session, dataset_id)
        label = dataset.name if dataset else f'#{dataset_id}'
        with page_shell(
            title='Edit Datapoint',
            breadcrumb_path=f'/datasets/{dataset_id}/rows/{datapoint_id}/edit',
            max_width_class='max-w-4xl',
            breadcrumb_items=[
                ('Home', '/'),
                ('Datasets', '/datasets'),
                (label, f'/datasets/{dataset_id}'),
                (f'Row #{datapoint_id}', None),
            ],
        ):
            _render_datapoint_form(engine, dataset_id, datapoint_id=datapoint_id)


def _render_dataset_list(engine) -> None:
    ui.label('Datasets').classes('text-h5')
    name_input = ui.input('Dataset name').classes('w-full')
    with ui.row().classes('gap-2'):
        ui.button(
            'Create Dataset',
            color='primary',
            on_click=lambda: _create_dataset_and_refresh(engine, str(name_input.value or '').strip()),
        )

    ui.separator()
    ui.label('Import CSV/XLSX').classes('text-h6')
    _render_dataset_import(engine)

    with Session(engine) as session:
        datasets = dataset_repo.list_datasets(session)

    ui.separator()
    if not datasets:
        ui.label('No datasets yet.')
        return

    for dataset in datasets:
        with ui.row().classes('w-full items-center justify-between border rounded p-2'):
            ui.label(dataset.name)
            with ui.row().classes('gap-1'):
                ui.button('Open', on_click=lambda did=dataset.id: ui.navigate.to(f'/datasets/{int(did)}')).props('flat')
                confirm_delete_button(
                    label='Delete',
                    item_name=f'dataset "{dataset.name}"',
                    on_confirm=lambda did=dataset.id: _delete_dataset_and_refresh(engine, int(did)),
                )


def _render_dataset_import(engine) -> None:
    status = ui.label('Upload a .csv or .xlsx file.').classes('text-caption text-grey-7')

    async def handle_upload(event: UploadEventArguments) -> None:
        suffix = Path(event.file.name).suffix.lower()
        if suffix not in {'.csv', '.xlsx', '.xlsm'}:
            status.set_text('Unsupported file type. Use .csv or .xlsx.')
            return

        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            temp_path = Path(tmp.name)
        await event.file.save(temp_path)

        try:
            parsed = dataset_import_service.parse_dataset_file(str(temp_path))
        except Exception as exc:
            status.set_text(f'Import parse failed: {exc}')
            return
        finally:
            try:
                temp_path.unlink(missing_ok=True)
            except Exception:
                pass

        status.set_text(f'Parsed {Path(event.file.name).name}: {len(parsed.rows)} rows, {len(parsed.field_names)} fields.')
        _open_import_dialog(engine, parsed, inferred_name=Path(event.file.name).stem.strip())

    ui.upload(on_upload=handle_upload, auto_upload=True).props('accept=.csv,.xlsx')


def _open_import_dialog(engine, parsed: dataset_import_service.ParsedDataset, inferred_name: str) -> None:
    with ui.dialog() as dialog, ui.card().classes('w-[90vw] max-w-5xl'):
        ui.label('Import Dataset').classes('text-h6')
        dataset_name_input = ui.input('Dataset name', value=inferred_name).classes('w-full')
        ui.label('Review inferred fields and choose types before testing import.').classes('text-caption text-grey-7')

        type_selects: dict[str, object] = {}
        for index, field_name in enumerate(parsed.field_names):
            inferred_type = parsed.inferred_types[field_name]
            sample = _sample_for_field(parsed.rows, index)
            with ui.row().classes('w-full items-center gap-2'):
                ui.label(field_name).classes('w-48')
                type_selects[field_name] = ui.select(
                    {t.value: t.value for t in DatasetFieldType},
                    value=inferred_type.value,
                    label='Type',
                ).classes('w-48')
                ui.label(f'sample: {sample}').classes('text-caption text-grey-7')

        status = ui.label('Click "Test" before creating dataset.').classes('text-caption text-grey-7')
        tested_payload: dict[str, object] = {'ready': False, 'signature': None, 'fields': None, 'rows': None, 'name': None}

        def current_signature() -> tuple[str, tuple[tuple[str, str], ...]]:
            dataset_name = str(dataset_name_input.value or '').strip()
            types = tuple(sorted((name, str(select.value)) for name, select in type_selects.items()))
            return dataset_name, types

        def invalidate_test_state() -> None:
            tested_payload['ready'] = False
            tested_payload['signature'] = None
            create_button.disable()
            status.set_text('Configuration changed. Click "Test" again.')

        dataset_name_input.on('update:model-value', lambda _: invalidate_test_state())
        for select in type_selects.values():
            select.on('update:model-value', lambda _: invalidate_test_state())

        def handle_test() -> None:
            dataset_name = str(dataset_name_input.value or '').strip()
            name_errors = dataset_service.validate_dataset_name(dataset_name)
            if name_errors:
                show_errors(error.message for error in name_errors)
                return

            try:
                selected_types = {
                    field_name: DatasetFieldType(str(select.value))
                    for field_name, select in type_selects.items()
                }
                converted_rows = dataset_import_service.validate_and_convert_rows(parsed, selected_types)
                fields = [
                    (
                        field_name,
                        selected_types[field_name],
                        idx,
                        converted_rows[0][field_name] if converted_rows else _zero_default(selected_types[field_name]),
                    )
                    for idx, field_name in enumerate(parsed.field_names)
                ]

                with Session(engine) as session:
                    dataset_repo.create_dataset_with_schema_and_rows(
                        session,
                        dataset_name=dataset_name,
                        fields=fields,
                        rows=converted_rows,
                        commit=False,
                    )
                    session.rollback()
            except IntegrityError:
                status.set_text('Test failed: dataset name must be globally unique.')
                ui.notify('Test failed: dataset name must be globally unique.', color='negative')
                return
            except Exception as exc:
                status.set_text(f'Test failed: {exc}')
                ui.notify(f'Test failed: {exc}', color='negative')
                return

            tested_payload['ready'] = True
            tested_payload['signature'] = current_signature()
            tested_payload['fields'] = fields
            tested_payload['rows'] = converted_rows
            tested_payload['name'] = dataset_name
            create_button.enable()
            status.set_text('Test passed. Everything loaded correctly. You can now create dataset.')
            ui.notify('Test passed.', color='positive')

        def handle_commit() -> None:
            if not bool(tested_payload.get('ready')):
                ui.notify('Please run Test first.', color='negative')
                return
            if tested_payload.get('signature') != current_signature():
                ui.notify('Configuration changed after test. Run Test again.', color='negative')
                create_button.disable()
                return

            try:
                with Session(engine) as session:
                    dataset_repo.create_dataset_with_schema_and_rows(
                        session,
                        dataset_name=str(tested_payload['name']),
                        fields=list(tested_payload['fields']),  # type: ignore[arg-type]
                        rows=list(tested_payload['rows']),  # type: ignore[arg-type]
                        commit=True,
                    )
            except IntegrityError:
                ui.notify('Create failed: dataset name must be globally unique.', color='negative')
                return
            except Exception as exc:
                ui.notify(f'Create failed: {exc}', color='negative')
                return

            ui.notify('Dataset imported.', color='positive')
            dialog.close()
            ui.navigate.to('/datasets')

        with ui.row().classes('justify-end w-full gap-2'):
            ui.button('Cancel', on_click=dialog.close).props('outline')
            ui.button('Test', on_click=handle_test).props('outline')
            create_button = ui.button('Create dataset', on_click=handle_commit, color='primary')
            create_button.disable()

    dialog.open()


def _sample_for_field(rows: list[list[object]], index: int) -> str:
    for row in rows:
        if index >= len(row):
            continue
        value = row[index]
        if value is None:
            continue
        text = str(value)
        if text.strip() == '':
            continue
        return text
    return '<empty>'


def _zero_default(field_type: DatasetFieldType):
    if field_type == DatasetFieldType._int:
        return 0
    if field_type == DatasetFieldType._float:
        return 0.0
    if field_type == DatasetFieldType._bool:
        return False
    return ''


def _render_dataset_detail(engine, dataset_id: int) -> None:
    with Session(engine) as session:
        dataset = dataset_repo.get_dataset(session, dataset_id)
        fields = dataset_repo.list_fields(session, dataset_id)
        datapoints = dataset_repo.list_datapoints(session, dataset_id)
        datapoint_values = {
            int(datapoint.id): dataset_repo.list_datapoint_values(session, int(datapoint.id))
            for datapoint in datapoints
            if datapoint.id is not None
        }
    if dataset is None:
        ui.label('Dataset not found.')
        return

    ui.label(f'Name: {dataset.name}').classes('text-subtitle1')

    ui.separator()
    ui.label('Fields').classes('text-h6')
    _render_field_create_form(engine, dataset_id, fields)
    if not fields:
        ui.label('No fields yet.')
    else:
        with ui.column().classes('w-full gap-1'):
            for field in fields:
                ui.label(
                    f'{field.order_index}. {field.name} [{field.field_type.value}] default={_field_default_str(field)}'
                ).classes('text-body2')
        ui.label('Field edit/delete is disabled by design.').classes('text-caption text-grey-7')

    ui.separator()
    ui.label('Datapoints').classes('text-h6')
    if not fields:
        ui.label('Add fields first to create datapoints.').classes('text-body2')
        return
    ui.button('Add Datapoint', on_click=lambda: ui.navigate.to(f'/datasets/{dataset_id}/rows/new'), color='primary').props('outline')
    if not datapoints:
        ui.label('No datapoints yet.')
        return

    field_by_id = {int(field.id): field for field in fields if field.id is not None}
    for datapoint in datapoints:
        if datapoint.id is None:
            continue
        values = {int(value.field_id): value for value in datapoint_values[int(datapoint.id)]}
        with ui.column().classes('w-full border rounded p-2 gap-1'):
            with ui.row().classes('w-full items-center justify-between'):
                ui.label(f'Row #{int(datapoint.id)}').classes('text-body1')
                with ui.row().classes('gap-1'):
                    ui.button(
                        'Edit',
                        on_click=lambda rid=datapoint.id: ui.navigate.to(f'/datasets/{dataset_id}/rows/{int(rid)}/edit'),
                    ).props('flat')
                    confirm_delete_button(
                        label='Delete',
                        item_name=f'row #{int(datapoint.id)}',
                        on_confirm=lambda rid=datapoint.id: _delete_datapoint_and_refresh(engine, dataset_id, int(rid)),
                    )
            for field in fields:
                field_id = int(field.id)
                value_row = values.get(field_id)
                if value_row is None:
                    value_text = '<missing>'
                else:
                    value_text = dataset_service.typed_value_to_string(field.field_type, value_row)
                ui.label(f'{field.name}: {value_text}').classes('text-caption')


def _render_field_create_form(engine, dataset_id: int, existing_fields) -> None:
    name_input = ui.input('Field name').classes('w-full')
    type_select = ui.select(
        {t.value: t.value for t in DatasetFieldType},
        value=DatasetFieldType._string.value,
        label='Field type',
    ).classes('w-full')
    default_input = ui.input('Default value (required)').classes('w-full')
    order_input = ui.number('order_index', value=len(existing_fields), step=1, precision=0).classes('w-full')

    def handle_create() -> None:
        name = str(name_input.value or '').strip()
        raw_type = str(type_select.value or '')
        default_raw = str(default_input.value or '')
        order_index = int(order_input.value or 0)
        errors = dataset_service.validate_field_payload(name, order_index, default_raw)
        if errors:
            show_errors(error.message for error in errors)
            return
        try:
            field_type = dataset_service.parse_field_type(raw_type)
            default_value = dataset_service.parse_typed_value(field_type, default_raw)
            with Session(engine) as session:
                dataset_repo.create_field(
                    session,
                    dataset_id=dataset_id,
                    name=name,
                    field_type=field_type,
                    order_index=order_index,
                    default_value=default_value,
                )
        except Exception as exc:
            ui.notify(str(exc), color='negative')
            return
        ui.notify('Field created.', color='positive')
        ui.navigate.to(f'/datasets/{dataset_id}')

    ui.button('Add Field', on_click=handle_create, color='primary').props('outline')


def _render_datapoint_form(engine, dataset_id: int, datapoint_id: int | None) -> None:
    with Session(engine) as session:
        dataset = dataset_repo.get_dataset(session, dataset_id)
        fields = dataset_repo.list_fields(session, dataset_id)
        existing_value_map: dict[int, object] = {}
        if datapoint_id is not None:
            datapoint = dataset_repo.get_datapoint(session, datapoint_id)
            if datapoint is None or int(datapoint.dataset_id) != dataset_id:
                ui.label('Datapoint not found.')
                ui.button('Back', on_click=lambda: ui.navigate.to(f'/datasets/{dataset_id}'))
                return
            for value_row in dataset_repo.list_datapoint_values(session, datapoint_id):
                field = next((f for f in fields if int(f.id) == int(value_row.field_id)), None)
                if field is None:
                    continue
                existing_value_map[int(field.id)] = dataset_service.typed_value_to_string(field.field_type, value_row)
    if dataset is None:
        ui.label('Dataset not found.')
        return
    if not fields:
        ui.label('No fields available.')
        return

    controls: dict[int, object] = {}
    for field in fields:
        field_id = int(field.id)
        initial = existing_value_map.get(field_id, _field_default_str(field))
        if field.field_type == DatasetFieldType._bool:
            bool_value = str(initial).strip().lower() in {'true', '1', 'yes', 'y', 't'}
            control = ui.switch(field.name, value=bool_value).classes('w-full')
        else:
            control = ui.input(f'{field.name} [{field.field_type.value}]', value=str(initial)).classes('w-full')
        controls[field_id] = control

    def handle_save() -> None:
        try:
            values_by_field_id: dict[int, object] = {}
            for field in fields:
                field_id = int(field.id)
                control = controls[field_id]
                if field.field_type == DatasetFieldType._bool:
                    parsed = bool(getattr(control, 'value', False))
                else:
                    raw = str(getattr(control, 'value', '')).strip()
                    if raw == '':
                        raise ValueError(f'Value is required for field "{field.name}".')
                    parsed = dataset_service.parse_typed_value(field.field_type, raw)
                values_by_field_id[field_id] = parsed

            field_ids = {int(field.id) for field in fields}
            if set(values_by_field_id.keys()) != field_ids:
                raise ValueError('Datapoint must include all dataset fields exactly once.')

            with Session(engine) as session:
                if datapoint_id is None:
                    dataset_repo.create_datapoint_with_values(
                        session,
                        dataset_id=dataset_id,
                        values_by_field_id=values_by_field_id,
                    )
                    ui.notify('Datapoint created.', color='positive')
                else:
                    dataset_repo.update_datapoint_values(
                        session,
                        datapoint_id=datapoint_id,
                        values_by_field_id=values_by_field_id,
                    )
                    ui.notify('Datapoint saved.', color='positive')
        except Exception as exc:
            ui.notify(str(exc), color='negative')
            return

        ui.navigate.to(f'/datasets/{dataset_id}')

    with ui.row().classes('gap-2'):
        ui.button('Save', on_click=handle_save, color='primary')
        ui.button('Back', on_click=lambda: ui.navigate.to(f'/datasets/{dataset_id}')).props('outline')


def _field_default_str(field) -> str:
    if field.field_type == DatasetFieldType._int:
        return str(field.default_int)
    if field.field_type == DatasetFieldType._float:
        return str(field.default_float)
    if field.field_type == DatasetFieldType._bool:
        return 'true' if field.default_bool else 'false'
    return field.default_string or ''


def _create_dataset_and_refresh(engine, name: str) -> None:
    errors = dataset_service.validate_dataset_name(name)
    if errors:
        show_errors(error.message for error in errors)
        return
    try:
        with Session(engine) as session:
            dataset_repo.create_dataset(session, name=name)
    except IntegrityError:
        ui.notify('Dataset name must be globally unique.', color='negative')
        return
    ui.notify('Dataset created.', color='positive')
    ui.navigate.to('/datasets')


def _delete_dataset_and_refresh(engine, dataset_id: int) -> None:
    with Session(engine) as session:
        dataset_repo.delete_dataset(session, dataset_id)
    ui.notify('Dataset deleted.', color='positive')
    ui.navigate.to('/datasets')


def _delete_datapoint_and_refresh(engine, dataset_id: int, datapoint_id: int) -> None:
    with Session(engine) as session:
        dataset_repo.delete_datapoint(session, datapoint_id)
    ui.notify('Datapoint deleted.', color='positive')
    ui.navigate.to(f'/datasets/{dataset_id}')
