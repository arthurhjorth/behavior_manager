from __future__ import annotations

from sqlmodel import Session, select

from models import (
    DatapointRecord,
    DatapointValueRecord,
    DatasetFieldRecord,
    DatasetFieldType,
    DatasetRecord,
    _coerce_dataset_value,
)


def list_datasets(session: Session) -> list[DatasetRecord]:
    return list(session.exec(select(DatasetRecord).order_by(DatasetRecord.name, DatasetRecord.id)))


def get_dataset(session: Session, dataset_id: int) -> DatasetRecord | None:
    return session.get(DatasetRecord, dataset_id)


def create_dataset(session: Session, name: str) -> DatasetRecord:
    row = DatasetRecord(name=name)
    session.add(row)
    session.commit()
    session.refresh(row)
    return row


def create_dataset_with_schema_and_rows(
    session: Session,
    *,
    dataset_name: str,
    fields: list[tuple[str, DatasetFieldType, int, object]],
    rows: list[dict[str, object]],
    commit: bool = True,
) -> DatasetRecord:
    dataset = DatasetRecord(name=dataset_name)
    session.add(dataset)
    session.flush()

    field_rows: list[DatasetFieldRecord] = []
    for field_name, field_type, order_index, default_value in fields:
        default_int, default_float, default_bool, default_string = _coerce_dataset_value(field_type, default_value)
        field = DatasetFieldRecord(
            dataset_id=int(dataset.id),
            name=field_name,
            field_type=field_type,
            order_index=order_index,
            default_int=default_int,
            default_float=default_float,
            default_bool=default_bool,
            default_string=default_string,
        )
        session.add(field)
        session.flush()
        field_rows.append(field)

    field_by_name = {field.name: field for field in field_rows}
    for row_data in rows:
        datapoint = DatapointRecord(dataset_id=int(dataset.id))
        session.add(datapoint)
        session.flush()
        for field_name, raw_value in row_data.items():
            field = field_by_name[field_name]
            value_int, value_float, value_bool, value_string = _coerce_dataset_value(field.field_type, raw_value)
            value_row = DatapointValueRecord(
                datapoint_id=int(datapoint.id),
                field_id=int(field.id),
                value_int=value_int,
                value_float=value_float,
                value_bool=value_bool,
                value_string=value_string,
            )
            session.add(value_row)

    if commit:
        session.commit()
        session.refresh(dataset)
    else:
        session.flush()
    return dataset


def delete_dataset(session: Session, dataset_id: int) -> None:
    row = session.get(DatasetRecord, dataset_id)
    if row is None:
        return

    for datapoint in list_datapoints(session, dataset_id):
        delete_datapoint(session, int(datapoint.id), commit=False)
    for field in list_fields(session, dataset_id):
        session.delete(field)

    session.delete(row)
    session.commit()


def list_fields(session: Session, dataset_id: int) -> list[DatasetFieldRecord]:
    statement = select(DatasetFieldRecord).where(DatasetFieldRecord.dataset_id == dataset_id).order_by(
        DatasetFieldRecord.order_index,
        DatasetFieldRecord.id,
    )
    return list(session.exec(statement))


def get_field(session: Session, field_id: int) -> DatasetFieldRecord | None:
    return session.get(DatasetFieldRecord, field_id)


def create_field(
    session: Session,
    *,
    dataset_id: int,
    name: str,
    field_type: DatasetFieldType,
    order_index: int,
    default_value,
) -> DatasetFieldRecord:
    default_int, default_float, default_bool, default_string = _coerce_dataset_value(field_type, default_value)
    row = DatasetFieldRecord(
        dataset_id=dataset_id,
        name=name,
        field_type=field_type,
        order_index=order_index,
        default_int=default_int,
        default_float=default_float,
        default_bool=default_bool,
        default_string=default_string,
    )
    session.add(row)
    session.commit()
    session.refresh(row)
    return row


def list_datapoints(session: Session, dataset_id: int) -> list[DatapointRecord]:
    statement = select(DatapointRecord).where(DatapointRecord.dataset_id == dataset_id).order_by(DatapointRecord.id)
    return list(session.exec(statement))


def get_datapoint(session: Session, datapoint_id: int) -> DatapointRecord | None:
    return session.get(DatapointRecord, datapoint_id)


def list_datapoint_values(session: Session, datapoint_id: int) -> list[DatapointValueRecord]:
    statement = (
        select(DatapointValueRecord)
        .where(DatapointValueRecord.datapoint_id == datapoint_id)
        .order_by(DatapointValueRecord.field_id, DatapointValueRecord.id)
    )
    return list(session.exec(statement))


def create_datapoint_with_values(
    session: Session,
    *,
    dataset_id: int,
    values_by_field_id: dict[int, object],
) -> DatapointRecord:
    datapoint = DatapointRecord(dataset_id=dataset_id)
    session.add(datapoint)
    session.commit()
    session.refresh(datapoint)

    fields = list_fields(session, dataset_id)
    field_map = {int(field.id): field for field in fields if field.id is not None}
    for field_id, value in values_by_field_id.items():
        field = field_map[field_id]
        value_int, value_float, value_bool, value_string = _coerce_dataset_value(field.field_type, value)
        value_row = DatapointValueRecord(
            datapoint_id=int(datapoint.id),
            field_id=field_id,
            value_int=value_int,
            value_float=value_float,
            value_bool=value_bool,
            value_string=value_string,
        )
        session.add(value_row)

    session.commit()
    session.refresh(datapoint)
    return datapoint


def update_datapoint_values(
    session: Session,
    *,
    datapoint_id: int,
    values_by_field_id: dict[int, object],
) -> None:
    datapoint = session.get(DatapointRecord, datapoint_id)
    if datapoint is None:
        raise ValueError(f"Datapoint {datapoint_id} not found")

    existing_values = {int(value.field_id): value for value in list_datapoint_values(session, datapoint_id)}
    fields = list_fields(session, int(datapoint.dataset_id))
    field_map = {int(field.id): field for field in fields if field.id is not None}

    for field_id, value in values_by_field_id.items():
        field = field_map[field_id]
        value_int, value_float, value_bool, value_string = _coerce_dataset_value(field.field_type, value)
        value_row = existing_values.get(field_id)
        if value_row is None:
            value_row = DatapointValueRecord(datapoint_id=datapoint_id, field_id=field_id)
        value_row.value_int = value_int
        value_row.value_float = value_float
        value_row.value_bool = value_bool
        value_row.value_string = value_string
        session.add(value_row)

    session.commit()


def delete_datapoint(session: Session, datapoint_id: int, *, commit: bool = True) -> None:
    datapoint = session.get(DatapointRecord, datapoint_id)
    if datapoint is None:
        return
    for value in list_datapoint_values(session, datapoint_id):
        session.delete(value)
    session.delete(datapoint)
    if commit:
        session.commit()
