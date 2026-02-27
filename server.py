from __future__ import annotations

from pathlib import Path

from nicegui import app, ui
from nicegui.events import UploadEventArguments
from sqlmodel import Session

from models import create_study, get_engine, init_db, list_studies
from ui.pages.decisions_page import register_decision_pages
from ui.pages.variables_page import register_variable_pages


STUDIES_DIR = Path('studies')
STUDIES_DIR.mkdir(parents=True, exist_ok=True)
init_db()
ENGINE = get_engine()
register_decision_pages(ENGINE)
register_variable_pages(ENGINE)


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
    with ui.column().classes('items-start gap-2 p-6'):
        ui.label('Behavior Manager').classes('text-h5')
        ui.link('Go to studies', '/studies/')
        ui.link('Go to decisions', '/decisions')
        ui.link('Go to variables', '/variables')


@ui.page('/studies/')
def studies_page() -> None:
    with ui.column().classes('w-full max-w-3xl p-6 gap-4'):
        ui.label('Studies').classes('text-h5')
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
                    if study.file_path:
                        ui.label(f'{study.name} ({Path(study.file_path).name})')
                    else:
                        ui.label(study.name)

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


if __name__ in {'__main__', '__mp_main__'}:
    ui.run(prod_js=False)
else:
    ui.run_with(app, prod_js=False)
