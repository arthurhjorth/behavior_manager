from __future__ import annotations

from nicegui import ui
from sqlmodel import Session

from repositories import decision_repo


def render_decision_detail(*, engine, decision_id: int) -> bool:
    with Session(engine) as session:
        decision = decision_repo.get_decision(session, decision_id)

    if decision is None:
        ui.label('Decision not found.')
        return False

    ui.label(decision.name).classes('text-h5')
    ui.label(decision.description).classes('text-body1')
    return True
