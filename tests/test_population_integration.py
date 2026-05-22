from __future__ import annotations

from io import BytesIO
import zipfile
import unittest

from openpyxl import Workbook
from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel, Session, create_engine, select

from models import (
    PopulationComparableValueKind,
    PopulationComparatorKind,
    PopulationDataKind,
    PopulationFeatureDistanceRecord,
    PopulationPersonRecord,
    PopulationQuestionRecord,
    PopulationQuestionRole,
    PopulationResponseRecord,
    PopulationTransformKind,
)
from repositories import population_matching_repo, population_repo
from services import netlogo_population_service, population_import_service, population_matching_service


def make_engine():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    return engine


def workbook_bytes(rows: list[list[object]], sheet_name: str = "Survey") -> bytes:
    workbook = Workbook()
    worksheet = workbook.active
    worksheet.title = sheet_name
    for row in rows:
        worksheet.append(row)
    stream = BytesIO()
    workbook.save(stream)
    return stream.getvalue()


def add_question(session: Session, study_id: int, external_id: str, wording: str) -> PopulationQuestionRecord:
    source_ref = population_repo.create_source_ref(file_path="fixture.xlsx", session=session, column_name=wording)
    return population_repo.create_question(
        session,
        PopulationQuestionRecord(
            external_id=external_id,
            study_id=study_id,
            source_ref_id=int(source_ref.id),
            kind=PopulationDataKind.numeric,
            wording=wording,
            short_name=wording,
            role=PopulationQuestionRole.demographic,
        ),
    )


def add_person(session: Session, study_id: int, external_id: str, source_person_id: str) -> PopulationPersonRecord:
    source_ref = population_repo.create_source_ref(file_path="fixture.xlsx", session=session)
    return population_repo.create_person(
        session,
        PopulationPersonRecord(
            external_id=external_id,
            study_id=study_id,
            source_ref_id=int(source_ref.id),
            source_person_id=source_person_id,
        ),
    )


def add_response(session: Session, person_id: int, question_id: int, value: object) -> None:
    source_ref = population_repo.create_source_ref(file_path="fixture.xlsx", session=session)
    population_repo.create_response(
        session,
        PopulationResponseRecord(
            person_id=person_id,
            question_id=question_id,
            source_ref_id=int(source_ref.id),
            **population_import_service.value_columns(value),
        ),
    )


class PopulationIntegrationTests(unittest.TestCase):
    def test_workbook_import_persists_study_and_is_rerunnable(self) -> None:
        engine = make_engine()
        content = workbook_bytes(
            [
                ["person_id", "age", "agree climate"],
                ["p1", 34, 5],
                ["p2", 41, 3],
            ]
        )

        with Session(engine) as session:
            result = population_import_service.import_workbook_bytes(
                session,
                filename="population_fixture.xlsx",
                content=content,
            )
            self.assertEqual(result.study_count, 1)
            self.assertEqual(result.question_count, 3)
            self.assertEqual(result.person_count, 2)

            study_id = result.study_ids[0]
            self.assertEqual(population_repo.count_people(session, study_id), 2)
            self.assertEqual(population_repo.count_questions(session, study_id), 3)

            rerun = population_import_service.import_workbook_bytes(
                session,
                filename="population_fixture.xlsx",
                content=content,
            )
            self.assertEqual(rerun.study_count, 0)
            self.assertEqual(rerun.question_count, 0)
            self.assertEqual(rerun.person_count, 0)

    def test_matching_service_finds_nearest_neighbor_and_persists_run_details(self) -> None:
        engine = make_engine()
        with Session(engine) as session:
            source = population_repo.create_study(
                session,
                external_id="source",
                name="Source",
                source_file="fixture.xlsx",
            )
            target = population_repo.create_study(
                session,
                external_id="target",
                name="Target",
                source_file="fixture.xlsx",
            )
            source_question = add_question(session, int(source.id), "source_age", "age")
            target_question = add_question(session, int(target.id), "target_age", "age")
            source_person = add_person(session, int(source.id), "source_p1", "s1")
            near_target = add_person(session, int(target.id), "target_p1", "t1")
            far_target = add_person(session, int(target.id), "target_p2", "t2")
            add_response(session, int(source_person.id), int(source_question.id), 20)
            add_response(session, int(near_target.id), int(target_question.id), 21)
            add_response(session, int(far_target.id), int(target_question.id), 90)
            session.commit()

            workspace = population_matching_repo.create_workspace(
                session,
                name="Fixture workspace",
                source_study_id=int(source.id),
                target_study_id=int(target.id),
            )
            population_matching_repo.create_mapping(
                session,
                workspace_id=int(workspace.id),
                name="age",
                left_study_id=int(source.id),
                right_study_id=int(target.id),
                left_inputs=[{"question_id": int(source_question.id), "alias": "age", "required": True}],
                right_inputs=[{"question_id": int(target_question.id), "alias": "age", "required": True}],
                left_transform={"kind": PopulationTransformKind.identity.value, "input_aliases": ["age"], "parameters": {}},
                right_transform={"kind": PopulationTransformKind.identity.value, "input_aliases": ["age"], "parameters": {}},
                comparator={"kind": PopulationComparatorKind.scaled_absolute_distance.value, "parameters": {"scale": 100}},
                output_kind=PopulationComparableValueKind.number,
                weight=1.0,
            )
            population_matching_repo.update_matching_defaults(
                session,
                int(workspace.id),
                source_study_id=int(source.id),
                target_study_id=int(target.id),
                k=1,
            )

            matches = population_matching_service.find_nearest_matches(
                session,
                workspace_id=int(workspace.id),
                source_person_id=int(source_person.id),
                source_study_id=int(source.id),
                target_study_id=int(target.id),
                k=1,
            )
            self.assertEqual(len(matches), 1)
            self.assertEqual(matches[0].target_person_id, int(near_target.id))
            self.assertAlmostEqual(matches[0].distance, 0.01)

            estimate = population_matching_service.estimate_from_neighbors(
                session,
                matches=matches,
                target_question_id=int(target_question.id),
            )
            self.assertAlmostEqual(estimate["estimate"], 21.0)

            run = population_matching_service.run_weighted_knn(session, workspace_id=int(workspace.id), source_limit=1).run
            self.assertEqual(run.match_count, 1)
            feature_rows = list(session.exec(select(PopulationFeatureDistanceRecord)))
            self.assertEqual(len(feature_rows), 1)
            self.assertEqual(feature_rows[0].mapping_name, "age")

    def test_netlogo_population_package_adds_csv_setup_and_owned_fields(self) -> None:
        engine = make_engine()
        model_text = """<?xml version="1.0" encoding="utf-8"?>
<model>
  <code><![CDATA[breed [ wolves wolf ]
wolves-own [ energy ]

to go
end
]]></code>
</model>"""
        with Session(engine) as session:
            study = population_repo.create_study(
                session,
                external_id="population",
                name="Population",
                source_file="fixture.xlsx",
            )
            age = add_question(session, int(study.id), "population_age", "Age")
            meat = add_question(session, int(study.id), "population_meat", "Meat intake")
            person = add_person(session, int(study.id), "population_p1", "p1")
            add_response(session, int(person.id), int(age.id), 34)
            add_response(session, int(person.id), int(meat.id), "low")
            session.commit()

            package = netlogo_population_service.build_population_package(
                session,
                model_text=model_text,
                model_filename="wolves.nlogox",
                study_id=int(study.id),
                question_ids=[int(age.id), int(meat.id)],
                agent_kind="wolves",
            )

        with zipfile.ZipFile(BytesIO(package.content)) as archive:
            names = set(archive.namelist())
            self.assertEqual(names, {"wolves.nlogox", "population_data.csv", "README.md"})
            generated_model = archive.read("wolves.nlogox").decode("utf-8")
            csv_text = archive.read("population_data.csv").decode("utf-8")

        self.assertIn("extensions [csv]", generated_model)
        self.assertIn("wolves-own [ energy age meat-intake ]", generated_model)
        self.assertIn("to setup-population-from-dataset", generated_model)
        self.assertIn("create-wolves 1", generated_model)
        self.assertIn('csv:from-file "population_data.csv"', generated_model)
        self.assertIn("age,meat-intake", csv_text)
        self.assertIn("34,low", csv_text)


if __name__ == "__main__":
    unittest.main()
