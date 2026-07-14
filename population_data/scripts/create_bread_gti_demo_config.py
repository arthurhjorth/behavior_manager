from __future__ import annotations

import hashlib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from matching_models import (
    AuditEvent,
    ComparableValueKind,
    ComparatorKind,
    ComparatorSpec,
    MappingInput,
    MatchingWorkspaceConfig,
    MissingPolicy,
    Note,
    TransformKind,
    TransformSpec,
    VariableSetMapping,
)


DATASET_PATH = ROOT / "outputs" / "population_data.json"
CONFIG_DIR = ROOT / "outputs" / "matching_configs"

BREAD_STUDY = "data_from_au_breadrescuer_study_1_only_dk_upcycled_bread_breadrescuers_completed__breadrescuers_completedataset_d"
GTI_STUDY = "data_from_au_green_transition_index_fall_2025_gti_w4only_cleaned_xlsx__gti_w4only_cleaned"

BREAD = {
    "age": f"{BREAD_STUDY}__q008_how_old_are_you",
    "gender": f"{BREAD_STUDY}__q009_which_gender_do_you_identify_with",
    "region": f"{BREAD_STUDY}__q012_region_in_denmark",
    "education": f"{BREAD_STUDY}__q102_what_is_your_highest_level_of_education_achieved",
    "household_type": f"{BREAD_STUDY}__q099_which_of_the_following_best_represents_your_curr",
    "household_size_category": f"{BREAD_STUDY}__q100_how_many_people_including_yourself_live_in_your",
    "children_category": f"{BREAD_STUDY}__q101_how_many_children_below_18_years_of_age_are_in_y",
    "cost_pressure": f"{BREAD_STUDY}__q103_to_what_extent_are_you_concerned_about_the_cost",
    "env_products_no_harm": f"{BREAD_STUDY}__q077_it_is_important_to_me_that_the_products_i_use_do",
    "env_purchase_habits": f"{BREAD_STUDY}__q078_my_purchase_habits_are_affected_by_my_concern_fo",
    "env_responsible_identity": f"{BREAD_STUDY}__q079_i_would_describe_myself_as_environmentally_respo",
    "env_inconvenience": f"{BREAD_STUDY}__q080_i_am_willing_to_be_inconvenienced_in_order_to_ta",
}

GTI = {
    "age": f"{GTI_STUDY}__q004_hvor_gammel_er_du",
    "gender": f"{GTI_STUDY}__q003_er_du",
    "region": f"{GTI_STUDY}__q007_region",
    "education": f"{GTI_STUDY}__q143_hvad_er_dit_uddannelsesniveau",
    "age_0_6": f"{GTI_STUDY}__q144_0_6_r_glem_ikke_at_inkludere_dig_selv_hvor_mange",
    "age_7_18": f"{GTI_STUDY}__q145_7_18_r_glem_ikke_at_inkludere_dig_selv_hvor_mang",
    "age_19_65": f"{GTI_STUDY}__q146_19_65_r_glem_ikke_at_inkludere_dig_selv_hvor_man",
    "age_66_plus": f"{GTI_STUDY}__q147_66_r_eller_derover_glem_ikke_at_inkludere_dig_se",
    "household_income": f"{GTI_STUDY}__q156_hvordan_vil_du_beskrive_din_husstandsindkomst",
    "env_products_no_harm": f"{GTI_STUDY}__q125_det_er_vigtigt_for_mig_at_de_produkter_jeg_bruge",
    "env_purchase_habits": f"{GTI_STUDY}__q126_mine_indk_bsvaner_er_p_virket_af_min_bekymring_f",
    "env_responsible_identity": f"{GTI_STUDY}__q127_jeg_vil_beskrive_mig_selv_som_milj_m_ssigt_ansva",
    "env_inconvenience": f"{GTI_STUDY}__q128_det_er_i_orden_for_mig_at_det_giver_ekstra_besv",
}


def dataset_fingerprint(path: Path) -> str:
    digest = hashlib.sha256()
    digest.update(path.name.encode("utf-8"))
    stat = path.stat()
    digest.update(str(stat.st_size).encode("utf-8"))
    digest.update(str(int(stat.st_mtime)).encode("utf-8"))
    return digest.hexdigest()[:16]


def mapping(
    *,
    name: str,
    description: str,
    left_inputs: list[MappingInput],
    right_inputs: list[MappingInput],
    left_transform: TransformSpec,
    right_transform: TransformSpec,
    comparator: ComparatorSpec,
    output_kind: ComparableValueKind,
    weight: float,
    notes: str | None = None,
) -> VariableSetMapping:
    return VariableSetMapping(
        name=name,
        description=description,
        left_study_id=BREAD_STUDY,
        right_study_id=GTI_STUDY,
        left_inputs=left_inputs,
        right_inputs=right_inputs,
        left_transform=left_transform,
        right_transform=right_transform,
        comparator=comparator,
        output_kind=output_kind,
        weight=weight,
        notes=notes,
    )


def normalized_likert_mapping(
    *,
    name: str,
    description: str,
    left_question_id: str,
    right_question_id: str,
    alias: str,
    notes: str | None = None,
) -> VariableSetMapping:
    return mapping(
        name=name,
        description=description,
        left_inputs=[MappingInput(question_id=left_question_id, alias=alias)],
        right_inputs=[MappingInput(question_id=right_question_id, alias=alias)],
        left_transform=TransformSpec(
            kind=TransformKind.NORMALIZE_MINMAX,
            input_aliases=[alias],
            parameters={"min": 1, "max": 7},
        ),
        right_transform=TransformSpec(
            kind=TransformKind.NORMALIZE_MINMAX,
            input_aliases=[alias],
            parameters={"min": 1, "max": 7},
        ),
        comparator=ComparatorSpec(kind=ComparatorKind.SCALED_ABSOLUTE_DISTANCE, parameters={"scale": 1}),
        output_kind=ComparableValueKind.NUMBER,
        weight=0.5,
        notes=notes,
    )


def build_config() -> MatchingWorkspaceConfig:
    config = MatchingWorkspaceConfig(
        config_id="config_breadrescuers_gti_demographic_ses_baseline",
        name="BreadRescuers <-> GTI demographic SES baseline",
        description=(
            "Mapping-only configuration for BreadRescuers and GTI. No matching has been run. "
            "Age is mapped only as exact numeric age; age-category variables are intentionally unused."
        ),
        dataset_path=str(DATASET_PATH.relative_to(ROOT)),
        dataset_fingerprint=dataset_fingerprint(DATASET_PATH),
        study_ids=[BREAD_STUDY, GTI_STUDY],
        primary_source_study_id=BREAD_STUDY,
        primary_target_study_id=GTI_STUDY,
    )

    config.matching_defaults.source_study_id = BREAD_STUDY
    config.matching_defaults.target_study_id = GTI_STUDY
    config.matching_defaults.notes = "Defaults only; this saved config has not been used to run matching."

    config.variable_set_mappings = [
        mapping(
            name="age_exact",
            description="Exact age in years on both sides. No age-category variables are used.",
            left_inputs=[MappingInput(question_id=BREAD["age"], alias="age")],
            right_inputs=[MappingInput(question_id=GTI["age"], alias="age")],
            left_transform=TransformSpec(kind=TransformKind.IDENTITY_NUMERIC, input_aliases=["age"]),
            right_transform=TransformSpec(kind=TransformKind.IDENTITY_NUMERIC, input_aliases=["age"]),
            comparator=ComparatorSpec(
                kind=ComparatorKind.SCALED_ABSOLUTE_DISTANCE,
                parameters={
                    "scale": 16,
                    "cap_at": 1,
                    "rationale": "BreadRescuers observed age range is 18-34; differences are divided by this 16-year span.",
                },
            ),
            output_kind=ComparableValueKind.NUMBER,
            weight=2.0,
            notes="Uses only exact age. The age-category item is deliberately excluded to avoid using age twice.",
        ),
        mapping(
            name="gender_recode",
            description="Recode both gender variables to shared categories.",
            left_inputs=[MappingInput(question_id=BREAD["gender"], alias="gender")],
            right_inputs=[MappingInput(question_id=GTI["gender"], alias="gender")],
            left_transform=TransformSpec(
                kind=TransformKind.CATEGORY_RECODE,
                input_aliases=["gender"],
                parameters={"mapping": {"1": "male", "2": "female", "3": "other", "4": "other"}},
            ),
            right_transform=TransformSpec(
                kind=TransformKind.CATEGORY_RECODE,
                input_aliases=["gender"],
                parameters={"mapping": {"1": "female", "2": "male", "3": "other", "4": None}},
            ),
            comparator=ComparatorSpec(kind=ComparatorKind.EXACT_MATCH),
            output_kind=ComparableValueKind.CATEGORY,
            weight=1.0,
        ),
        mapping(
            name="region_exact",
            description="Danish region coded on the same 1-5 scale in both studies.",
            left_inputs=[MappingInput(question_id=BREAD["region"], alias="region")],
            right_inputs=[MappingInput(question_id=GTI["region"], alias="region")],
            left_transform=TransformSpec(kind=TransformKind.IDENTITY_CATEGORY, input_aliases=["region"]),
            right_transform=TransformSpec(kind=TransformKind.IDENTITY_CATEGORY, input_aliases=["region"]),
            comparator=ComparatorSpec(kind=ComparatorKind.EXACT_MATCH),
            output_kind=ComparableValueKind.CATEGORY,
            weight=1.0,
        ),
        mapping(
            name="education_ordinal",
            description="Highest education is treated as an aligned 1-5 ordinal scale.",
            left_inputs=[MappingInput(question_id=BREAD["education"], alias="education")],
            right_inputs=[MappingInput(question_id=GTI["education"], alias="education")],
            left_transform=TransformSpec(
                kind=TransformKind.NORMALIZE_MINMAX,
                input_aliases=["education"],
                parameters={"min": 1, "max": 5},
            ),
            right_transform=TransformSpec(
                kind=TransformKind.NORMALIZE_MINMAX,
                input_aliases=["education"],
                parameters={"min": 1, "max": 5},
            ),
            comparator=ComparatorSpec(kind=ComparatorKind.SCALED_ABSOLUTE_DISTANCE, parameters={"scale": 1}),
            output_kind=ComparableValueKind.NUMBER,
            weight=1.25,
        ),
        mapping(
            name="household_composition_demo",
            description="Demo of matching a set of household variables to another set of household age-count variables.",
            left_inputs=[
                MappingInput(question_id=BREAD["household_type"], alias="household_type", required=False),
                MappingInput(question_id=BREAD["household_size_category"], alias="household_size_category", required=False),
                MappingInput(question_id=BREAD["children_category"], alias="children_category", required=False),
            ],
            right_inputs=[
                MappingInput(question_id=GTI["age_0_6"], alias="age_0_6", required=False),
                MappingInput(question_id=GTI["age_7_18"], alias="age_7_18", required=False),
                MappingInput(question_id=GTI["age_19_65"], alias="age_19_65", required=False),
                MappingInput(question_id=GTI["age_66_plus"], alias="age_66_plus", required=False),
            ],
            left_transform=TransformSpec(
                kind=TransformKind.CUSTOM,
                input_aliases=["household_type", "household_size_category", "children_category"],
                output_alias="household_composition",
                parameters={
                    "custom_kind": "bread_household_to_adults_children",
                    "intended_output": {"adults": "numeric_or_interval", "children": "numeric_or_interval"},
                    "household_type_labels": {
                        "1": "single",
                        "2": "couple",
                        "3": "family",
                        "4": "unrelated_adults",
                        "5": "other",
                    },
                    "household_size_category_labels": {
                        "1": "2 people",
                        "2": "3-4 people",
                        "3": "5+ people",
                    },
                    "children_category_labels": {"1": "1 child", "2": "2 children", "3": "3+ children"},
                    "note": "Stored as a demo transform spec. Review interval and midpoint rules before production matching.",
                },
            ),
            right_transform=TransformSpec(
                kind=TransformKind.COLLAPSE_HOUSEHOLD_AGE_COUNTS,
                input_aliases=["age_0_6", "age_7_18", "age_19_65", "age_66_plus"],
                output_alias="household_composition",
                parameters={
                    "children_aliases": ["age_0_6", "age_7_18"],
                    "adult_aliases": ["age_19_65", "age_66_plus"],
                },
            ),
            comparator=ComparatorSpec(
                kind=ComparatorKind.WEIGHTED_COMPONENT_DISTANCE,
                parameters={
                    "components": {
                        "adults": {"weight": 1, "scale": 4},
                        "children": {"weight": 1, "scale": 3},
                    }
                },
                missing_policy=MissingPolicy.PAIRWISE_IGNORE,
            ),
            output_kind=ComparableValueKind.OBJECT,
            weight=1.25,
            notes="Included to demonstrate a set-of-variables transformation. It is mapping metadata only at this stage.",
        ),
        mapping(
            name="income_cost_pressure_proxy",
            description="Low-weight SES proxy: Bread cost-of-living concern against GTI household income.",
            left_inputs=[MappingInput(question_id=BREAD["cost_pressure"], alias="cost_pressure")],
            right_inputs=[MappingInput(question_id=GTI["household_income"], alias="household_income")],
            left_transform=TransformSpec(
                kind=TransformKind.NORMALIZE_MINMAX,
                input_aliases=["cost_pressure"],
                parameters={"min": 1, "max": 7, "missing_values": [99]},
            ),
            right_transform=TransformSpec(
                kind=TransformKind.NORMALIZE_MINMAX,
                input_aliases=["household_income"],
                parameters={
                    "min": 1,
                    "max": 4,
                    "reverse": True,
                    "rationale": "Higher income is expected to correspond to lower cost pressure.",
                },
            ),
            comparator=ComparatorSpec(kind=ComparatorKind.SCALED_ABSOLUTE_DISTANCE, parameters={"scale": 1}),
            output_kind=ComparableValueKind.NUMBER,
            weight=0.5,
            notes="Related but not equivalent variables, so this is intentionally low weight.",
        ),
        normalized_likert_mapping(
            name="environment_products_no_harm",
            description="Environmental concern item: products used should not harm the environment.",
            left_question_id=BREAD["env_products_no_harm"],
            right_question_id=GTI["env_products_no_harm"],
            alias="products_no_harm_environment",
            notes="Individual 1-7 item mapping. Bread q081 average is intentionally excluded to avoid double-counting.",
        ),
        normalized_likert_mapping(
            name="environment_purchase_habits",
            description="Environmental concern item: purchase habits are affected by environmental concern.",
            left_question_id=BREAD["env_purchase_habits"],
            right_question_id=GTI["env_purchase_habits"],
            alias="purchase_habits_environment",
            notes="Individual 1-7 item mapping. Weight is 0.5 so the four environmental items together count as one stronger construct.",
        ),
        normalized_likert_mapping(
            name="environment_responsible_identity",
            description="Environmental concern item: self-description as environmentally responsible.",
            left_question_id=BREAD["env_responsible_identity"],
            right_question_id=GTI["env_responsible_identity"],
            alias="environmentally_responsible_identity",
            notes="Individual 1-7 item mapping. Weight is 0.5 so this preserves the attitude profile without overwhelming demographics.",
        ),
        normalized_likert_mapping(
            name="environment_inconvenience",
            description="Environmental concern item: willingness to accept inconvenience to be environmentally friendly.",
            left_question_id=BREAD["env_inconvenience"],
            right_question_id=GTI["env_inconvenience"],
            alias="environmental_inconvenience_acceptance",
            notes="Individual 1-7 item mapping. This is the fourth item in the environmental concern block.",
        ),
    ]

    config.notes.append(
        Note(
            text=(
                "Initial manual mapping config for BreadRescuers and GTI. "
                "Do not use age twice: only exact numeric age is included."
            ),
            tags=["manual", "demo", "no-match-run"],
        )
    )
    config.audit_events.append(
        AuditEvent(
            event_type="config_created",
            message="Created BreadRescuers-GTI mapping-only config with exact-age-only age mapping.",
        )
    )
    config.touch()
    return config


def main() -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    for path in CONFIG_DIR.glob("*.json"):
        path.unlink()

    config = build_config()
    output_path = CONFIG_DIR / f"{config.config_id}.json"
    output_path.write_text(config.model_dump_json(indent=2), encoding="utf-8")

    MatchingWorkspaceConfig.model_validate_json(output_path.read_text(encoding="utf-8"))
    print(output_path.relative_to(ROOT))
    print(f"{len(config.variable_set_mappings)} mappings")


if __name__ == "__main__":
    main()
