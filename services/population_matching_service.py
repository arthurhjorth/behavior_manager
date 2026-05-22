from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from statistics import median
from typing import Any, Iterable
from uuid import uuid4

from sqlmodel import Session, select

from models import (
    PopulationComparatorKind,
    PopulationFeatureDistanceRecord,
    PopulationMappingStatus,
    PopulationMatchRunRecord,
    PopulationPersonMatchRecord,
    PopulationPersonRecord,
    PopulationQuestionRecord,
    PopulationResponseRecord,
    PopulationTransformKind,
    PopulationVariableSetMappingRecord,
)
from repositories import population_matching_repo, population_repo


@dataclass(frozen=True)
class MatchingInput:
    question_id: int
    question_external_id: str
    alias: str
    required: bool = True


@dataclass(frozen=True)
class TransformSpec:
    kind: PopulationTransformKind
    input_aliases: list[str]
    parameters: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ComparatorSpec:
    kind: PopulationComparatorKind
    parameters: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class VariableMapping:
    id: int
    external_id: str
    name: str
    left_study_id: int
    right_study_id: int
    left_inputs: list[MatchingInput]
    right_inputs: list[MatchingInput]
    left_transform: TransformSpec
    right_transform: TransformSpec
    comparator: ComparatorSpec
    weight: float


@dataclass(frozen=True)
class PersonData:
    id: int
    external_id: str
    study_id: int
    source_person_id: str | None
    values_by_question_external_id: dict[str, Any]


@dataclass(frozen=True)
class FeatureDistance:
    mapping_id: int
    mapping_external_id: str
    mapping_name: str
    distance: float | None
    weight: float
    source_value: Any = None
    target_value: Any = None
    missing: bool = False


@dataclass(frozen=True)
class PersonMatch:
    source_person_id: int
    source_person_external_id: str
    target_person_id: int
    target_person_external_id: str
    distance: float
    similarity: float
    matched_features_count: int
    missing_features_count: int
    feature_distances: list[FeatureDistance] = field(default_factory=list)


@dataclass(frozen=True)
class MatchingRunResult:
    run: PopulationMatchRunRecord
    matches: list[PersonMatch]


def active_mappings(session: Session, workspace_id: int) -> list[VariableMapping]:
    workspace_study_ids = {row.study_id for row in population_matching_repo.list_workspace_studies(session, workspace_id)}
    mappings = []
    for mapping in population_matching_repo.list_mappings(session, workspace_id):
        if mapping.status != PopulationMappingStatus.approved:
            continue
        if {mapping.left_study_id, mapping.right_study_id} != workspace_study_ids:
            continue
        loaded = _load_mapping(session, mapping)
        if loaded is not None:
            mappings.append(loaded)
    return mappings


def run_weighted_knn(
    session: Session,
    *,
    workspace_id: int,
    source_limit: int | None = 25,
) -> MatchingRunResult:
    workspace = population_matching_repo.get_workspace(session, workspace_id)
    defaults = population_matching_repo.get_matching_defaults(session, workspace_id)
    if workspace is None or defaults is None or defaults.source_study_id is None or defaults.target_study_id is None:
        raise ValueError("Workspace needs source and target study defaults.")
    mappings = active_mappings(session, workspace_id)
    if not mappings:
        raise ValueError("Workspace needs at least one approved mapping.")
    source_people = load_people(session, defaults.source_study_id, limit=source_limit)
    target_people = load_people(session, defaults.target_study_id)
    matches: list[PersonMatch] = []
    for source_person in source_people:
        matches.extend(_nearest_for_person(source_person, target_people, mappings, defaults.source_study_id, defaults.k))
    summary = {
        "source_people_evaluated": len(source_people),
        "target_people_available": len(target_people),
        "approved_mappings_used": len(mappings),
        "match_count": len(matches),
        "average_distance": sum(match.distance for match in matches) / len(matches) if matches else None,
    }
    run = PopulationMatchRunRecord(
        external_id=f"run_{uuid4().hex[:12]}",
        workspace_id=workspace_id,
        source_study_id=defaults.source_study_id,
        target_study_id=defaults.target_study_id,
        method=defaults.method,
        k=defaults.k,
        source_people_evaluated=summary["source_people_evaluated"],
        target_people_available=summary["target_people_available"],
        approved_mappings_used=summary["approved_mappings_used"],
        match_count=summary["match_count"],
        average_distance=summary["average_distance"],
        summary_json=population_repo.json_dump(summary),
    )
    session.add(run)
    session.flush()
    _persist_matches(session, run, matches)
    population_matching_repo.add_audit_event(session, workspace_id, "match", f"Ran weighted kNN matching {run.external_id}")
    session.commit()
    session.refresh(run)
    return MatchingRunResult(run=run, matches=matches)


def find_nearest_matches(
    session: Session,
    *,
    workspace_id: int,
    source_person_id: int,
    source_study_id: int,
    target_study_id: int,
    k: int,
    excluded_mapping_ids: set[int] | None = None,
) -> list[PersonMatch]:
    source_person = load_person(session, source_person_id)
    if source_person is None or source_person.study_id != source_study_id:
        raise ValueError("Source person does not belong to the selected source study.")
    mappings = [mapping for mapping in active_mappings(session, workspace_id) if mapping.id not in (excluded_mapping_ids or set())]
    return _nearest_for_person(source_person, load_people(session, target_study_id), mappings, source_study_id, k)


def estimate_from_neighbors(
    session: Session,
    *,
    matches: Iterable[PersonMatch],
    target_question_id: int,
) -> dict[str, Any]:
    question = session.get(PopulationQuestionRecord, target_question_id)
    if question is None:
        raise ValueError("Question not found.")
    observations: list[dict[str, Any]] = []
    for match in matches:
        person = load_person(session, match.target_person_id)
        if person is None:
            continue
        value = person.values_by_question_external_id.get(question.external_id)
        if value is None:
            continue
        observations.append(
            {
                "person_id": person.id,
                "person_external_id": person.external_id,
                "value": value,
                "weight": max(match.similarity, 0.001),
                "distance": match.distance,
            }
        )
    if not observations:
        return {"kind": question.kind.value, "estimate": None, "method": "no observed neighbor values", "observations": []}
    numeric = [(to_float(item["value"]), item["weight"]) for item in observations]
    numeric = [(value, weight) for value, weight in numeric if value is not None]
    if question.kind.value in {"numeric", "ordinal", "likert"} and numeric:
        total_weight = sum(weight for _, weight in numeric)
        return {
            "kind": question.kind.value,
            "estimate": sum(value * weight for value, weight in numeric) / total_weight if total_weight else None,
            "method": "similarity-weighted mean",
            "observations": observations,
        }
    weighted_counts: dict[str, float] = {}
    raw_by_label: dict[str, Any] = {}
    for item in observations:
        label = str(item["value"])
        weighted_counts[label] = weighted_counts.get(label, 0.0) + item["weight"]
        raw_by_label[label] = item["value"]
    label = max(weighted_counts.items(), key=lambda item: item[1])[0]
    return {
        "kind": question.kind.value,
        "estimate": raw_by_label[label],
        "method": "similarity-weighted vote",
        "weighted_counts": weighted_counts,
        "observations": observations,
    }


def validate_mapping_for_person(
    session: Session,
    *,
    workspace_id: int,
    source_person_id: int,
    source_study_id: int,
    target_study_id: int,
    mapping_id: int,
    k: int,
) -> dict[str, Any] | None:
    mapping = next((item for item in active_mappings(session, workspace_id) if item.id == mapping_id), None)
    if mapping is None or len(mapping.left_inputs) != 1 or len(mapping.right_inputs) != 1:
        raise ValueError("Validation requires an approved one-to-one mapping.")
    source_person = load_person(session, source_person_id)
    if source_person is None:
        return None
    if mapping.left_study_id == source_study_id:
        actual = mapping.left_inputs[0]
        counterpart = mapping.right_inputs[0]
    else:
        actual = mapping.right_inputs[0]
        counterpart = mapping.left_inputs[0]
    actual_value = source_person.values_by_question_external_id.get(actual.question_external_id)
    if actual_value is None:
        return None
    matches = find_nearest_matches(
        session,
        workspace_id=workspace_id,
        source_person_id=source_person_id,
        source_study_id=source_study_id,
        target_study_id=target_study_id,
        k=k,
        excluded_mapping_ids={mapping.id},
    )
    estimate = estimate_from_neighbors(session, matches=matches, target_question_id=counterpart.question_id)
    estimated_value = estimate.get("estimate")
    actual_number = to_float(actual_value)
    estimate_number = to_float(estimated_value)
    comparison = {"actual": actual_value, "estimate": estimated_value, "error": None, "exact_match": None}
    if actual_number is not None and estimate_number is not None:
        comparison["error"] = abs(actual_number - estimate_number)
    elif actual_value is not None and estimated_value is not None:
        comparison["exact_match"] = str(actual_value).lower() == str(estimated_value).lower()
    return {"mapping": mapping, "matches": matches, "estimate": estimate, "comparison": comparison}


def validate_mapping_population(
    session: Session,
    *,
    workspace_id: int,
    source_study_id: int,
    target_study_id: int,
    mapping_id: int,
    k: int,
    source_limit: int | None = None,
) -> dict[str, Any]:
    cases = []
    numeric_errors: list[float] = []
    exact_results: list[bool] = []
    for person in load_people(session, source_study_id, limit=source_limit):
        case = validate_mapping_for_person(
            session,
            workspace_id=workspace_id,
            source_person_id=person.id,
            source_study_id=source_study_id,
            target_study_id=target_study_id,
            mapping_id=mapping_id,
            k=k,
        )
        if case is None:
            continue
        comparison = case["comparison"]
        if comparison["error"] is not None:
            numeric_errors.append(float(comparison["error"]))
        if comparison["exact_match"] is not None:
            exact_results.append(bool(comparison["exact_match"]))
        cases.append(case)
    summary: dict[str, Any] = {
        "cases_evaluated": len(cases),
        "estimates_found": sum(1 for case in cases if case["estimate"].get("estimate") is not None),
    }
    if numeric_errors:
        summary.update(
            {
                "mean_absolute_error": sum(numeric_errors) / len(numeric_errors),
                "median_absolute_error": median(numeric_errors),
                "max_absolute_error": max(numeric_errors),
            }
        )
    if exact_results:
        summary.update(
            {
                "exact_match_rate": sum(1 for result in exact_results if result) / len(exact_results),
                "exact_match_count": sum(1 for result in exact_results if result),
                "exact_match_total": len(exact_results),
            }
        )
    return {"cases": cases, "summary": summary}


def load_people(session: Session, study_id: int, limit: int | None = None) -> list[PersonData]:
    statement = select(PopulationPersonRecord).where(PopulationPersonRecord.study_id == study_id).order_by(PopulationPersonRecord.id)
    if limit is not None:
        statement = statement.limit(limit)
    return [_load_person_row(session, person) for person in session.exec(statement)]


def load_person(session: Session, person_id: int) -> PersonData | None:
    row = session.get(PopulationPersonRecord, person_id)
    return _load_person_row(session, row) if row else None


def transform_value(values: dict[str, Any], spec: TransformSpec) -> Any:
    selected = {alias: values.get(alias) for alias in spec.input_aliases}
    first_value = next(iter(selected.values()), None)
    if spec.kind in {
        PopulationTransformKind.identity,
        PopulationTransformKind.identity_numeric,
        PopulationTransformKind.identity_category,
    }:
        return first_value if len(selected) == 1 else selected
    if spec.kind == PopulationTransformKind.normalize_minmax:
        value = to_float(first_value)
        low = spec.parameters.get("min")
        high = spec.parameters.get("max")
        if value is None or low is None or high is None or high == low:
            return value
        return (value - float(low)) / (float(high) - float(low))
    if spec.kind == PopulationTransformKind.category_to_interval:
        return spec.parameters.get("intervals", {}).get(str(first_value))
    if spec.kind in {PopulationTransformKind.category_recode, PopulationTransformKind.binary_recode}:
        return spec.parameters.get("mapping", {}).get(str(first_value), first_value)
    if spec.kind == PopulationTransformKind.multi_input_vector:
        return selected
    if spec.kind == PopulationTransformKind.derive_adults_children:
        household_size = to_float(selected.get("household_size"))
        children = to_float(selected.get("children"))
        if household_size is None or children is None:
            return None
        return {"adults": max(household_size - children, 0), "children": children}
    if spec.kind == PopulationTransformKind.collapse_household_age_counts:
        children = sum(to_float(selected.get(alias)) or 0 for alias in spec.parameters.get("children_aliases", []))
        adults = sum(to_float(selected.get(alias)) or 0 for alias in spec.parameters.get("adult_aliases", []))
        return {"adults": adults, "children": children}
    return selected


def compare_values(left: Any, right: Any, spec: ComparatorSpec) -> float | None:
    if left is None or right is None:
        return None
    if spec.kind == PopulationComparatorKind.exact_match:
        return 0.0 if str(left).lower() == str(right).lower() else 1.0
    if spec.kind == PopulationComparatorKind.binary_mismatch:
        return 0.0 if bool(left) == bool(right) else 1.0
    if spec.kind == PopulationComparatorKind.scaled_absolute_distance:
        left_num, right_num = to_float(left), to_float(right)
        if left_num is None or right_num is None:
            return None
        scale = float(spec.parameters.get("scale", 1.0) or 1.0)
        return min(abs(left_num - right_num) / scale, 1.0)
    if spec.kind == PopulationComparatorKind.numeric_to_interval_distance:
        return _numeric_interval_distance(left, right, spec.parameters)
    if spec.kind == PopulationComparatorKind.interval_overlap_distance:
        return _interval_overlap_distance(left, right, spec.parameters)
    if spec.kind == PopulationComparatorKind.jaccard_distance:
        left_set = set(left if isinstance(left, list) else str(left).split(","))
        right_set = set(right if isinstance(right, list) else str(right).split(","))
        left_set = {str(item).strip().lower() for item in left_set if str(item).strip()}
        right_set = {str(item).strip().lower() for item in right_set if str(item).strip()}
        return None if not left_set and not right_set else 1.0 - len(left_set & right_set) / max(len(left_set | right_set), 1)
    if spec.kind == PopulationComparatorKind.weighted_component_distance:
        return _weighted_component_distance(left, right, spec.parameters)
    return None


def compute_match_distance(
    source_person: PersonData,
    target_person: PersonData,
    mappings: Iterable[VariableMapping],
    source_study_id: int,
) -> tuple[float | None, list[FeatureDistance], int, int]:
    details = [evaluate_mapping(source_person, target_person, mapping, source_study_id) for mapping in mappings]
    total_weight = sum(detail.weight for detail in details if detail.distance is not None)
    if total_weight == 0:
        return None, details, 0, len(details)
    distance = sum((detail.distance or 0.0) * detail.weight for detail in details if detail.distance is not None) / total_weight
    matched = sum(1 for detail in details if detail.distance is not None)
    return distance, details, matched, len(details) - matched


def evaluate_mapping(
    source_person: PersonData,
    target_person: PersonData,
    mapping: VariableMapping,
    source_study_id: int,
) -> FeatureDistance:
    if mapping.left_study_id == source_study_id:
        source_inputs, source_transform = mapping.left_inputs, mapping.left_transform
        target_inputs, target_transform = mapping.right_inputs, mapping.right_transform
    else:
        source_inputs, source_transform = mapping.right_inputs, mapping.right_transform
        target_inputs, target_transform = mapping.left_inputs, mapping.left_transform
    source_values, source_missing = _collect_inputs(source_person, source_inputs)
    target_values, target_missing = _collect_inputs(target_person, target_inputs)
    transformed_source = transform_value(source_values, source_transform) if not source_missing else None
    transformed_target = transform_value(target_values, target_transform) if not target_missing else None
    distance = compare_values(transformed_source, transformed_target, mapping.comparator)
    return FeatureDistance(
        mapping_id=mapping.id,
        mapping_external_id=mapping.external_id,
        mapping_name=mapping.name,
        distance=distance,
        weight=mapping.weight,
        source_value=transformed_source,
        target_value=transformed_target,
        missing=distance is None,
    )


def to_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def interval_bounds(value: Any) -> tuple[float | None, float | None] | None:
    if not isinstance(value, list | tuple) or len(value) != 2:
        return None
    return to_float(value[0]), to_float(value[1]) if value[1] is not None else None


def summarize_neighbor_values(values: Iterable[Any]) -> str:
    observed = [value for value in values if value is not None]
    if not observed:
        return "no observed values"
    numbers = [to_float(value) for value in observed]
    if all(value is not None for value in numbers):
        numeric = [value for value in numbers if value is not None]
        return f"n={len(numeric)} mean={sum(numeric) / len(numeric):.3f} min={min(numeric):.3f} max={max(numeric):.3f}"
    label, count = Counter(str(value) for value in observed).most_common(1)[0]
    return f"n={len(observed)} mode={label} share={count / len(observed):.3f}"


def _load_mapping(session: Session, row: PopulationVariableSetMappingRecord) -> VariableMapping | None:
    questions = {
        int(question.id): question
        for question in session.exec(select(PopulationQuestionRecord))
        if question.id is not None
    }
    inputs = population_matching_repo.list_mapping_inputs(session, int(row.id))
    left_inputs = [_input_from_row(input_row, questions) for input_row in inputs if input_row.side == "left"]
    right_inputs = [_input_from_row(input_row, questions) for input_row in inputs if input_row.side == "right"]
    transforms = {transform.side: transform for transform in population_matching_repo.list_mapping_transforms(session, int(row.id))}
    comparator = population_matching_repo.get_mapping_comparator(session, int(row.id))
    if any(item is None for item in left_inputs + right_inputs) or "left" not in transforms or "right" not in transforms or comparator is None:
        return None
    return VariableMapping(
        id=int(row.id),
        external_id=row.external_id,
        name=row.name,
        left_study_id=row.left_study_id,
        right_study_id=row.right_study_id,
        left_inputs=[item for item in left_inputs if item],
        right_inputs=[item for item in right_inputs if item],
        left_transform=_transform_from_row(session, transforms["left"]),
        right_transform=_transform_from_row(session, transforms["right"]),
        comparator=ComparatorSpec(
            kind=comparator.kind,
            parameters=population_matching_repo.read_parameters(session, comparator_id=int(comparator.id)),
        ),
        weight=row.weight,
    )


def _input_from_row(row, questions: dict[int, PopulationQuestionRecord]) -> MatchingInput | None:
    question = questions.get(row.question_id)
    if question is None:
        return None
    return MatchingInput(
        question_id=row.question_id,
        question_external_id=question.external_id,
        alias=row.alias,
        required=row.required,
    )


def _transform_from_row(session: Session, row) -> TransformSpec:
    return TransformSpec(
        kind=row.kind,
        input_aliases=population_matching_repo.list_transform_aliases(session, int(row.id)),
        parameters=population_matching_repo.read_parameters(session, transform_id=int(row.id)),
    )


def _load_person_row(session: Session, person: PopulationPersonRecord) -> PersonData:
    response_rows = list(
        session.exec(select(PopulationResponseRecord).where(PopulationResponseRecord.person_id == person.id))
    )
    question_ids = {response.question_id for response in response_rows}
    questions = {
        int(question.id): question.external_id
        for question in session.exec(select(PopulationQuestionRecord).where(PopulationQuestionRecord.id.in_(question_ids)))
        if question.id is not None
    }
    values = {
        questions[response.question_id]: None
        if response.is_missing
        else population_repo.json_load(response.normalized_json, None)
        for response in response_rows
        if response.question_id in questions
    }
    return PersonData(
        id=int(person.id),
        external_id=person.external_id,
        study_id=person.study_id,
        source_person_id=person.source_person_id,
        values_by_question_external_id=values,
    )


def _nearest_for_person(
    source_person: PersonData,
    target_people: Iterable[PersonData],
    mappings: list[VariableMapping],
    source_study_id: int,
    k: int,
) -> list[PersonMatch]:
    candidates = []
    for target_person in target_people:
        distance, details, matched, missing = compute_match_distance(source_person, target_person, mappings, source_study_id)
        if distance is None:
            continue
        candidates.append(
            PersonMatch(
                source_person_id=source_person.id,
                source_person_external_id=source_person.external_id,
                target_person_id=target_person.id,
                target_person_external_id=target_person.external_id,
                distance=distance,
                similarity=1.0 - distance,
                matched_features_count=matched,
                missing_features_count=missing,
                feature_distances=details,
            )
        )
    return sorted(candidates, key=lambda match: match.distance)[: max(int(k), 1)]


def _collect_inputs(person: PersonData, inputs: Iterable[MatchingInput]) -> tuple[dict[str, Any], bool]:
    values = {}
    missing_required = False
    for item in inputs:
        value = person.values_by_question_external_id.get(item.question_external_id)
        values[item.alias] = value
        if value is None and item.required:
            missing_required = True
    return values, missing_required


def _persist_matches(session: Session, run: PopulationMatchRunRecord, matches: Iterable[PersonMatch]) -> None:
    ranks: dict[int, int] = {}
    for match in matches:
        ranks[match.source_person_id] = ranks.get(match.source_person_id, 0) + 1
        row = PopulationPersonMatchRecord(
            run_id=int(run.id),
            source_person_id=match.source_person_id,
            target_person_id=match.target_person_id,
            distance=match.distance,
            similarity=match.similarity,
            matched_features_count=match.matched_features_count,
            missing_features_count=match.missing_features_count,
            rank=ranks[match.source_person_id],
        )
        session.add(row)
        session.flush()
        for detail in match.feature_distances:
            session.add(
                PopulationFeatureDistanceRecord(
                    person_match_id=int(row.id),
                    mapping_id=detail.mapping_id,
                    mapping_external_id=detail.mapping_external_id,
                    mapping_name=detail.mapping_name,
                    distance=detail.distance,
                    weight=detail.weight,
                    source_value_json=population_repo.json_dump(detail.source_value),
                    target_value_json=population_repo.json_dump(detail.target_value),
                    missing=detail.missing,
                )
            )


def _numeric_interval_distance(left: Any, right: Any, parameters: dict[str, Any]) -> float | None:
    left_num = to_float(left)
    if left_num is None:
        interval = interval_bounds(left)
        value = to_float(right)
    else:
        interval = interval_bounds(right)
        value = left_num
    if interval is None or value is None:
        return None
    low, high = interval
    scale = float(parameters.get("scale", 100.0) or 100.0)
    if low is not None and value < low:
        return min((low - value) / scale, 1.0)
    if high is not None and value > high:
        return min((value - high) / scale, 1.0)
    return 0.0


def _interval_overlap_distance(left: Any, right: Any, parameters: dict[str, Any]) -> float | None:
    left_interval, right_interval = interval_bounds(left), interval_bounds(right)
    if left_interval is None or right_interval is None or left_interval[0] is None or right_interval[0] is None:
        return None
    left_low, left_high = left_interval
    right_low, right_high = right_interval
    left_high = left_high if left_high is not None else float(parameters.get("open_upper_bound", 120))
    right_high = right_high if right_high is not None else float(parameters.get("open_upper_bound", 120))
    intersection = max(0.0, min(left_high, right_high) - max(left_low, right_low))
    union = max(left_high, right_high) - min(left_low, right_low)
    return 1.0 - (intersection / union if union else 0.0)


def _weighted_component_distance(left: Any, right: Any, parameters: dict[str, Any]) -> float | None:
    if not isinstance(left, dict) or not isinstance(right, dict):
        return None
    total_weight = 0.0
    weighted = 0.0
    for key, options in parameters.get("components", {}).items():
        left_num, right_num = to_float(left.get(key)), to_float(right.get(key))
        if left_num is None or right_num is None:
            continue
        weight = float(options.get("weight", 1.0))
        scale = float(options.get("scale", 1.0) or 1.0)
        weighted += weight * min(abs(left_num - right_num) / scale, 1.0)
        total_weight += weight
    return weighted / total_weight if total_weight else None
