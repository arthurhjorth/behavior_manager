from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from hashlib import sha256
from statistics import median
from pathlib import Path
from typing import Any

import orjson
from nicegui import ui

from matching_models import (
    AuditEvent,
    ComparatorKind,
    ComparatorSpec,
    ComparableValueKind,
    FeatureDistance,
    MappingInput,
    MappingStatus,
    MatchRunResult,
    MatchingConfig,
    MatchingWorkspaceConfig,
    Note,
    PersonMatch,
    TransformKind,
    TransformSpec,
    VariableSetMapping,
    new_id,
)


ROOT = Path(__file__).resolve().parent
DATA_PATH = ROOT / "outputs" / "population_data.json"
CONFIG_DIR = ROOT / "outputs" / "matching_configs"
RUN_DIR = ROOT / "outputs" / "matching_runs"
PAGE_SIZE = 50
INPUT_SLOTS = 4


@dataclass(frozen=True)
class StudySummary:
    id: str
    name: str
    source_file: str
    source_sheet: str | None
    person_count: int
    question_count: int


class PopulationStore:
    def __init__(self, path: Path) -> None:
        raw = orjson.loads(path.read_bytes())
        self.metadata: dict[str, Any] = raw.get("metadata", {})
        self.studies: dict[str, dict[str, Any]] = {study["id"]: study for study in raw.get("studies", [])}
        self.questions: dict[str, dict[str, Any]] = {question["id"]: question for question in raw.get("questions", [])}
        self.questions_by_study: dict[str, list[dict[str, Any]]] = {}
        for question in self.questions.values():
            self.questions_by_study.setdefault(question["study_id"], []).append(question)
        self.people_by_study: dict[str, list[dict[str, Any]]] = {}
        for person in raw.get("people", []):
            self.people_by_study.setdefault(person["study_id"], []).append(person)
        self.study_summaries = [
            StudySummary(
                id=study_id,
                name=study.get("name") or study_id,
                source_file=study.get("source_file") or "",
                source_sheet=study.get("source_sheet"),
                person_count=len(self.people_by_study.get(study_id, [])),
                question_count=len(self.questions_by_study.get(study_id, [])),
            )
            for study_id, study in self.studies.items()
            if self.people_by_study.get(study_id)
        ]
        self.study_summaries.sort(key=lambda item: item.name.lower())


store = PopulationStore(DATA_PATH)


def dataset_fingerprint(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def short_text(value: Any, limit: int = 90) -> str:
    text = "" if value is None else " ".join(str(value).split())
    return text if len(text) <= limit else f"{text[: limit - 1]}..."


def study_name(study_id: str | None) -> str:
    if not study_id:
        return "None"
    return store.studies.get(study_id, {}).get("name", study_id)


def study_options() -> dict[str, str]:
    return {study.id: study.name for study in store.study_summaries}


def question_study_options() -> dict[str, str]:
    options = {
        study_id: store.studies.get(study_id, {}).get("name") or study_id
        for study_id in store.questions_by_study
        if store.questions_by_study.get(study_id)
    }
    return dict(sorted(options.items(), key=lambda item: item[1].lower()))


def question_options(study_id: str | None) -> dict[str, str]:
    if not study_id:
        return {}
    return {
        question["id"]: f"{index}. {short_text(question.get('wording'), 120)}"
        for index, question in enumerate(store.questions_by_study.get(study_id, []), start=1)
    }


def transform_options() -> dict[str, str]:
    return {
        TransformKind.IDENTITY.value: "Identity: return raw value",
        TransformKind.IDENTITY_NUMERIC.value: "Identity numeric",
        TransformKind.IDENTITY_CATEGORY.value: "Identity category",
        TransformKind.NORMALIZE_MINMAX.value: "Normalize min-max",
        TransformKind.CATEGORY_TO_INTERVAL.value: "Category to interval",
        TransformKind.CATEGORY_RECODE.value: "Category recode",
        TransformKind.BINARY_RECODE.value: "Binary recode",
        TransformKind.MULTI_INPUT_VECTOR.value: "Multi-input vector/object",
        TransformKind.DERIVE_ADULTS_CHILDREN.value: "Derive adults/children",
        TransformKind.COLLAPSE_HOUSEHOLD_AGE_COUNTS.value: "Collapse household age counts",
        TransformKind.CUSTOM.value: "Custom/manual transform",
    }


def comparator_options() -> dict[str, str]:
    return {
        ComparatorKind.SCALED_ABSOLUTE_DISTANCE.value: "Scaled absolute distance",
        ComparatorKind.EXACT_MATCH.value: "Exact match",
        ComparatorKind.BINARY_MISMATCH.value: "Binary mismatch",
        ComparatorKind.JACCARD_DISTANCE.value: "Jaccard distance",
        ComparatorKind.NUMERIC_TO_INTERVAL_DISTANCE.value: "Numeric to interval distance",
        ComparatorKind.INTERVAL_OVERLAP_DISTANCE.value: "Interval overlap distance",
        ComparatorKind.WEIGHTED_COMPONENT_DISTANCE.value: "Weighted component distance",
        ComparatorKind.CUSTOM.value: "Custom/manual comparator",
    }


def output_kind_options() -> dict[str, str]:
    return {kind.value: kind.value for kind in ComparableValueKind}


def config_path(config: MatchingWorkspaceConfig) -> Path:
    return CONFIG_DIR / f"{config.config_id}.json"


def save_config(config: MatchingWorkspaceConfig, message: str = "Saved configuration") -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    config.touch()
    config.audit_events.append(AuditEvent(event_type="save", message=message))
    config_path(config).write_text(
        config.model_dump_json(indent=2, exclude_none=True, ensure_ascii=False),
        encoding="utf-8",
    )


def load_configs() -> list[MatchingWorkspaceConfig]:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    configs: list[MatchingWorkspaceConfig] = []
    for path in sorted(CONFIG_DIR.glob("*.json")):
        config = MatchingWorkspaceConfig.model_validate_json(path.read_text(encoding="utf-8"))
        if config.schema_version == "0.2.0" and len(config.study_ids) == 2:
            configs.append(config)
    return configs


def create_config(name: str, left_study_id: str, right_study_id: str) -> MatchingWorkspaceConfig:
    config = MatchingWorkspaceConfig(
        name=name,
        description="Pair-specific variable-set mapping and matching configuration.",
        dataset_path=DATA_PATH.relative_to(ROOT).as_posix(),
        dataset_fingerprint=dataset_fingerprint(DATA_PATH),
        study_ids=[left_study_id, right_study_id],
        primary_source_study_id=left_study_id,
        primary_target_study_id=right_study_id,
        matching_defaults=MatchingConfig(source_study_id=left_study_id, target_study_id=right_study_id, k=5),
    )
    config.audit_events.append(AuditEvent(event_type="create", message="Created variable-set config"))
    save_config(config, "Created variable-set config")
    return config


def first_config() -> MatchingWorkspaceConfig:
    configs = load_configs()
    if configs:
        return configs[0]
    studies = [study.id for study in store.study_summaries]
    return create_config("Default variable-set config", studies[0], studies[1])


workspace_config = first_config()


class AppState:
    active_view: str = "studies"
    selected_study_id: str | None = store.study_summaries[0].id if store.study_summaries else None
    selected_person_id: str | None = None
    selected_question_study_id: str | None = next(iter(store.questions_by_study), None)
    question_filter: str = ""
    person_query: str = ""
    response_query: str = ""
    page: int = 0

    new_config_name: str = "New variable-set config"
    new_config_left_id: str | None = store.study_summaries[0].id if store.study_summaries else None
    new_config_right_id: str | None = store.study_summaries[1].id if len(store.study_summaries) > 1 else None

    mapping_name: str = ""
    mapping_description: str = ""
    left_question_ids: list[str | None] = [None] * INPUT_SLOTS
    left_aliases: list[str] = [""] * INPUT_SLOTS
    left_required: list[bool] = [True] * INPUT_SLOTS
    right_question_ids: list[str | None] = [None] * INPUT_SLOTS
    right_aliases: list[str] = [""] * INPUT_SLOTS
    right_required: list[bool] = [True] * INPUT_SLOTS
    left_transform_kind: str = TransformKind.IDENTITY.value
    right_transform_kind: str = TransformKind.IDENTITY.value
    left_transform_parameters: str = "{}"
    right_transform_parameters: str = "{}"
    comparator_kind: str = ComparatorKind.EXACT_MATCH.value
    comparator_parameters: str = "{}"
    output_kind: str = ComparableValueKind.NUMBER.value
    mapping_weight: float = 1.0
    mapping_notes: str = ""

    note_text: str = ""
    match_limit: int = 25
    last_run: MatchRunResult | None = None
    live_source_study_id: str | None = None
    live_source_person_id: str | None = None
    live_k: int = 5
    live_matches: list[PersonMatch] = []
    estimate_source_study_id: str | None = None
    estimate_source_person_id: str | None = None
    estimate_question_id: str | None = None
    estimate_k: int = 5
    estimate_result: dict[str, Any] | None = None
    estimation_mode: str = "estimate_missing"
    validation_source_study_id: str | None = None
    validation_source_person_id: str | None = None
    validation_question_id: str | None = None
    validation_k: int = 5
    validation_scope: str = "person"
    validation_result: dict[str, Any] | None = None


state = AppState()
if state.selected_study_id:
    people = store.people_by_study.get(state.selected_study_id, [])
    state.selected_person_id = people[0].get("id") if people else None


def config_options() -> dict[str, str]:
    return {
        config.config_id: f"{config.name} ({study_name(config.primary_source_study_id)} ↔ {study_name(config.primary_target_study_id)})"
        for config in load_configs()
    }


def config_left_id() -> str | None:
    return workspace_config.primary_source_study_id


def config_right_id() -> str | None:
    return workspace_config.primary_target_study_id


def set_active_view(view: str) -> None:
    state.active_view = view
    body_panel.refresh()


def display_value(value: dict[str, Any] | None) -> str:
    if not value or value.get("is_missing"):
        return ""
    raw = value.get("raw")
    if raw is None:
        return ""
    if isinstance(raw, bool):
        return "Yes" if raw else "No"
    return str(raw)


def parse_json_object(text: str, label: str) -> dict[str, Any] | None:
    try:
        parsed = orjson.loads((text or "{}").encode("utf-8"))
    except orjson.JSONDecodeError as exc:
        ui.notify(f"{label} must be valid JSON: {exc}", type="negative")
        return None
    if not isinstance(parsed, dict):
        ui.notify(f"{label} must be a JSON object", type="negative")
        return None
    return parsed


def selected_people() -> list[dict[str, Any]]:
    if state.selected_study_id is None:
        return []
    people = store.people_by_study.get(state.selected_study_id, [])
    query = state.person_query.strip().lower()
    if not query:
        return people
    return [
        person
        for person in people
        if query in str(person.get("source_person_id", "")).lower()
        or query in person.get("id", "").lower()
    ]


def selected_person() -> dict[str, Any] | None:
    if state.selected_study_id is None or state.selected_person_id is None:
        return None
    for person in store.people_by_study.get(state.selected_study_id, []):
        if person.get("id") == state.selected_person_id:
            return person
    return None


def select_study(study_id: str) -> None:
    state.selected_study_id = study_id
    state.person_query = ""
    state.response_query = ""
    state.page = 0
    people = store.people_by_study.get(study_id, [])
    state.selected_person_id = people[0].get("id") if people else None
    body_panel.refresh()


def select_question_study(study_id: str) -> None:
    state.selected_question_study_id = study_id
    state.question_filter = ""
    body_panel.refresh()


def select_person(person_id: str) -> None:
    state.selected_person_id = person_id
    state.response_query = ""
    body_panel.refresh()


def page_delta(delta: int) -> None:
    people = selected_people()
    max_page = max((len(people) - 1) // PAGE_SIZE, 0)
    state.page = min(max(state.page + delta, 0), max_page)
    body_panel.refresh()


def load_workspace_config(config_id: str) -> None:
    global workspace_config
    for config in load_configs():
        if config.config_id == config_id:
            workspace_config = config
            reset_mapping_form()
            state.live_source_study_id = None
            state.live_source_person_id = None
            state.live_matches = []
            state.estimate_source_study_id = None
            state.estimate_source_person_id = None
            state.estimate_question_id = None
            state.estimate_result = None
            state.validation_source_study_id = None
            state.validation_source_person_id = None
            state.validation_question_id = None
            state.validation_scope = "person"
            state.validation_result = None
            ensure_live_state_defaults()
            ui.notify("Configuration loaded", type="positive")
            body_panel.refresh()
            return
    ui.notify("Configuration not found", type="negative")


def create_workspace_from_form() -> None:
    global workspace_config
    if not state.new_config_left_id or not state.new_config_right_id:
        ui.notify("Choose two studies first", type="warning")
        return
    if state.new_config_left_id == state.new_config_right_id:
        ui.notify("Choose two different studies", type="warning")
        return
    workspace_config = create_config(
        state.new_config_name.strip() or "New variable-set config",
        state.new_config_left_id,
        state.new_config_right_id,
    )
    reset_mapping_form()
    state.live_source_study_id = None
    state.live_source_person_id = None
    state.live_matches = []
    state.estimate_source_study_id = None
    state.estimate_source_person_id = None
    state.estimate_question_id = None
    state.estimate_result = None
    state.validation_source_study_id = None
    state.validation_source_person_id = None
    state.validation_question_id = None
    state.validation_scope = "person"
    state.validation_result = None
    ensure_live_state_defaults()
    ui.notify("Configuration created", type="positive")
    body_panel.refresh()


def save_workspace() -> None:
    save_config(workspace_config)
    ui.notify("Configuration saved", type="positive")


def reset_mapping_form() -> None:
    state.mapping_name = ""
    state.mapping_description = ""
    state.left_question_ids = [None] * INPUT_SLOTS
    state.left_aliases = [""] * INPUT_SLOTS
    state.left_required = [True] * INPUT_SLOTS
    state.right_question_ids = [None] * INPUT_SLOTS
    state.right_aliases = [""] * INPUT_SLOTS
    state.right_required = [True] * INPUT_SLOTS
    state.left_transform_kind = TransformKind.IDENTITY.value
    state.right_transform_kind = TransformKind.IDENTITY.value
    state.left_transform_parameters = "{}"
    state.right_transform_parameters = "{}"
    state.comparator_kind = ComparatorKind.EXACT_MATCH.value
    state.comparator_parameters = "{}"
    state.output_kind = ComparableValueKind.NUMBER.value
    state.mapping_weight = 1.0
    state.mapping_notes = ""


def make_inputs(question_ids: list[str | None], aliases: list[str], required: list[bool], side: str) -> list[MappingInput] | None:
    inputs: list[MappingInput] = []
    seen: set[str] = set()
    for index, question_id in enumerate(question_ids):
        if not question_id:
            continue
        alias = aliases[index].strip() or f"{side}_{len(inputs) + 1}"
        if alias in seen:
            ui.notify(f"Duplicate {side} input alias: {alias}", type="warning")
            return None
        seen.add(alias)
        inputs.append(MappingInput(question_id=question_id, alias=alias, required=required[index]))
    return inputs


def save_variable_set_mapping() -> None:
    left_inputs = make_inputs(state.left_question_ids, state.left_aliases, state.left_required, "left")
    right_inputs = make_inputs(state.right_question_ids, state.right_aliases, state.right_required, "right")
    if left_inputs is None or right_inputs is None:
        return
    if not left_inputs or not right_inputs:
        ui.notify("Choose at least one input on each side", type="warning")
        return
    left_params = parse_json_object(state.left_transform_parameters, "Left transform parameters")
    right_params = parse_json_object(state.right_transform_parameters, "Right transform parameters")
    comparator_params = parse_json_object(state.comparator_parameters, "Comparator parameters")
    if left_params is None or right_params is None or comparator_params is None:
        return

    mapping = VariableSetMapping(
        name=state.mapping_name.strip() or f"Mapping {len(workspace_config.variable_set_mappings) + 1}",
        description=state.mapping_description.strip() or None,
        left_study_id=config_left_id() or "",
        right_study_id=config_right_id() or "",
        left_inputs=left_inputs,
        right_inputs=right_inputs,
        left_transform=TransformSpec(
            kind=TransformKind(state.left_transform_kind),
            input_aliases=[item.alias for item in left_inputs],
            output_alias="left_value",
            parameters=left_params,
        ),
        right_transform=TransformSpec(
            kind=TransformKind(state.right_transform_kind),
            input_aliases=[item.alias for item in right_inputs],
            output_alias="right_value",
            parameters=right_params,
        ),
        comparator=ComparatorSpec(
            kind=ComparatorKind(state.comparator_kind),
            parameters=comparator_params,
        ),
        output_kind=ComparableValueKind(state.output_kind),
        weight=float(state.mapping_weight or 1.0),
        notes=state.mapping_notes.strip() or None,
    )
    workspace_config.variable_set_mappings.append(mapping)
    save_config(workspace_config, "Saved variable-set mapping")
    reset_mapping_form()
    ui.notify("Variable-set mapping saved", type="positive")
    body_panel.refresh()


def disable_mapping(mapping_id: str) -> None:
    for mapping in workspace_config.variable_set_mappings:
        if mapping.mapping_id == mapping_id:
            mapping.status = MappingStatus.DISABLED
            save_config(workspace_config, "Disabled variable-set mapping")
            ui.notify("Mapping disabled", type="positive")
            body_panel.refresh()
            return


def add_note() -> None:
    text = state.note_text.strip()
    if not text:
        return
    workspace_config.notes.append(Note(text=text))
    state.note_text = ""
    save_config(workspace_config, "Added note")
    body_panel.refresh()


def person_response_map(person: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {response["question_id"]: response for response in person.get("responses", [])}


def raw_response_value(response: dict[str, Any] | None) -> Any:
    if not response:
        return None
    value = response.get("value", {})
    if value.get("is_missing"):
        return None
    return value.get("normalized", value.get("raw"))


def collect_inputs(person: dict[str, Any], inputs: list[MappingInput]) -> tuple[dict[str, Any], bool]:
    responses = person_response_map(person)
    values: dict[str, Any] = {}
    missing_required = False
    for item in inputs:
        value = raw_response_value(responses.get(item.question_id))
        if value is None and item.required:
            missing_required = True
        values[item.alias] = value
    return values, missing_required


def to_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def transform_value(values: dict[str, Any], spec: TransformSpec) -> Any:
    selected = {alias: values.get(alias) for alias in spec.input_aliases}
    first_value = next(iter(selected.values()), None)
    if spec.kind in {TransformKind.IDENTITY, TransformKind.IDENTITY_NUMERIC, TransformKind.IDENTITY_CATEGORY}:
        return first_value if len(selected) == 1 else selected
    if spec.kind == TransformKind.NORMALIZE_MINMAX:
        value = to_float(first_value)
        min_value = spec.parameters.get("min")
        max_value = spec.parameters.get("max")
        if value is None or min_value is None or max_value is None or max_value == min_value:
            return value
        return (value - float(min_value)) / (float(max_value) - float(min_value))
    if spec.kind == TransformKind.CATEGORY_TO_INTERVAL:
        intervals = spec.parameters.get("intervals", {})
        interval = intervals.get(str(first_value))
        return interval if interval is not None else None
    if spec.kind in {TransformKind.CATEGORY_RECODE, TransformKind.BINARY_RECODE}:
        mapping = spec.parameters.get("mapping", {})
        return mapping.get(str(first_value), first_value)
    if spec.kind == TransformKind.MULTI_INPUT_VECTOR:
        return selected
    if spec.kind == TransformKind.DERIVE_ADULTS_CHILDREN:
        household_size = to_float(selected.get("household_size"))
        children = to_float(selected.get("children"))
        if household_size is None or children is None:
            return None
        return {"adults": max(household_size - children, 0), "children": children}
    if spec.kind == TransformKind.COLLAPSE_HOUSEHOLD_AGE_COUNTS:
        children_aliases = spec.parameters.get("children_aliases", [])
        adult_aliases = spec.parameters.get("adult_aliases", [])
        children = sum(to_float(selected.get(alias)) or 0 for alias in children_aliases)
        adults = sum(to_float(selected.get(alias)) or 0 for alias in adult_aliases)
        return {"adults": adults, "children": children}
    return selected


def interval_bounds(value: Any) -> tuple[float | None, float | None] | None:
    if not isinstance(value, list | tuple) or len(value) != 2:
        return None
    low = to_float(value[0])
    high = to_float(value[1]) if value[1] is not None else None
    return low, high


def compare_values(left: Any, right: Any, spec: ComparatorSpec) -> float | None:
    if left is None or right is None:
        return None
    if spec.kind == ComparatorKind.EXACT_MATCH:
        return 0.0 if str(left).lower() == str(right).lower() else 1.0
    if spec.kind == ComparatorKind.BINARY_MISMATCH:
        return 0.0 if bool(left) == bool(right) else 1.0
    if spec.kind == ComparatorKind.SCALED_ABSOLUTE_DISTANCE:
        left_num = to_float(left)
        right_num = to_float(right)
        if left_num is None or right_num is None:
            return None
        scale = float(spec.parameters.get("scale", 1.0) or 1.0)
        return min(abs(left_num - right_num) / scale, 1.0)
    if spec.kind == ComparatorKind.NUMERIC_TO_INTERVAL_DISTANCE:
        left_num = to_float(left)
        interval = interval_bounds(right)
        if left_num is None:
            left_interval = interval_bounds(left)
            right_num = to_float(right)
            if left_interval is None or right_num is None:
                return None
            low, high = left_interval
            value = right_num
        else:
            if interval is None:
                return None
            low, high = interval
            value = left_num
        scale = float(spec.parameters.get("scale", 100.0) or 100.0)
        if low is not None and value < low:
            return min((low - value) / scale, 1.0)
        if high is not None and value > high:
            return min((value - high) / scale, 1.0)
        return 0.0
    if spec.kind == ComparatorKind.INTERVAL_OVERLAP_DISTANCE:
        left_interval = interval_bounds(left)
        right_interval = interval_bounds(right)
        if left_interval is None or right_interval is None:
            return None
        left_low, left_high = left_interval
        right_low, right_high = right_interval
        if left_low is None or right_low is None:
            return None
        left_high = left_high if left_high is not None else float(spec.parameters.get("open_upper_bound", 120))
        right_high = right_high if right_high is not None else float(spec.parameters.get("open_upper_bound", 120))
        intersection = max(0.0, min(left_high, right_high) - max(left_low, right_low))
        union = max(left_high, right_high) - min(left_low, right_low)
        return 1.0 - (intersection / union if union else 0.0)
    if spec.kind == ComparatorKind.JACCARD_DISTANCE:
        left_set = set(left if isinstance(left, list) else str(left).split(","))
        right_set = set(right if isinstance(right, list) else str(right).split(","))
        left_set = {str(item).strip().lower() for item in left_set if str(item).strip()}
        right_set = {str(item).strip().lower() for item in right_set if str(item).strip()}
        if not left_set and not right_set:
            return None
        return 1.0 - len(left_set & right_set) / max(len(left_set | right_set), 1)
    if spec.kind == ComparatorKind.WEIGHTED_COMPONENT_DISTANCE:
        if not isinstance(left, dict) or not isinstance(right, dict):
            return None
        components = spec.parameters.get("components", {})
        total_weight = 0.0
        weighted = 0.0
        for key, options in components.items():
            weight = float(options.get("weight", 1.0))
            scale = float(options.get("scale", 1.0) or 1.0)
            left_num = to_float(left.get(key))
            right_num = to_float(right.get(key))
            if left_num is None or right_num is None:
                continue
            weighted += weight * min(abs(left_num - right_num) / scale, 1.0)
            total_weight += weight
        return weighted / total_weight if total_weight else None
    return None


def active_mappings() -> list[VariableSetMapping]:
    return [
        mapping
        for mapping in workspace_config.variable_set_mappings
        if mapping.status == MappingStatus.APPROVED
        and {mapping.left_study_id, mapping.right_study_id} == set(workspace_config.study_ids)
    ]


def evaluate_mapping(
    source_person: dict[str, Any],
    target_person: dict[str, Any],
    mapping: VariableSetMapping,
    source_study_id: str,
) -> FeatureDistance:
    if mapping.left_study_id == source_study_id:
        source_inputs, source_transform = mapping.left_inputs, mapping.left_transform
        target_inputs, target_transform = mapping.right_inputs, mapping.right_transform
    else:
        source_inputs, source_transform = mapping.right_inputs, mapping.right_transform
        target_inputs, target_transform = mapping.left_inputs, mapping.left_transform
    source_values, source_missing = collect_inputs(source_person, source_inputs)
    target_values, target_missing = collect_inputs(target_person, target_inputs)
    transformed_source = transform_value(source_values, source_transform) if not source_missing else None
    transformed_target = transform_value(target_values, target_transform) if not target_missing else None
    distance = compare_values(transformed_source, transformed_target, mapping.comparator)
    return FeatureDistance(
        mapping_id=mapping.mapping_id,
        mapping_name=mapping.name,
        distance=distance,
        weight=mapping.weight,
        source_value=transformed_source,
        target_value=transformed_target,
        missing=distance is None,
    )


def compute_match_distance(
    source_person: dict[str, Any],
    target_person: dict[str, Any],
    mappings: list[VariableSetMapping],
    source_study_id: str,
) -> tuple[float | None, list[FeatureDistance], int, int]:
    details = [evaluate_mapping(source_person, target_person, mapping, source_study_id) for mapping in mappings]
    total_weight = sum(detail.weight for detail in details if detail.distance is not None)
    if total_weight == 0:
        return None, details, 0, len(details)
    distance = sum((detail.distance or 0) * detail.weight for detail in details if detail.distance is not None) / total_weight
    matched = sum(1 for detail in details if detail.distance is not None)
    missing = sum(1 for detail in details if detail.distance is None)
    return distance, details, matched, missing


def run_matching() -> None:
    source_study_id = workspace_config.matching_defaults.source_study_id or config_left_id()
    target_study_id = workspace_config.matching_defaults.target_study_id or config_right_id()
    if not source_study_id or not target_study_id or source_study_id == target_study_id:
        ui.notify("This config needs two different studies", type="warning")
        return
    mappings = active_mappings()
    if not mappings:
        ui.notify("Add at least one approved variable-set mapping first", type="warning")
        return
    source_people = store.people_by_study.get(source_study_id, [])[: state.match_limit]
    target_people = store.people_by_study.get(target_study_id, [])
    matches: list[PersonMatch] = []
    for source_person in source_people:
        candidates = []
        for target_person in target_people:
            distance, details, matched, missing = compute_match_distance(source_person, target_person, mappings, source_study_id)
            if distance is not None:
                candidates.append((distance, target_person, details, matched, missing))
        for distance, target_person, details, matched, missing in sorted(candidates, key=lambda item: item[0])[
            : workspace_config.matching_defaults.k
        ]:
            matches.append(
                PersonMatch(
                    source_person_id=source_person["id"],
                    target_person_id=target_person["id"],
                    distance=distance,
                    similarity=1.0 - distance,
                    matched_features_count=matched,
                    missing_features_count=missing,
                    feature_distances=details,
                )
            )
    result = MatchRunResult(
        config_id=workspace_config.config_id,
        source_study_id=source_study_id,
        target_study_id=target_study_id,
        method=workspace_config.matching_defaults.method,
        k=workspace_config.matching_defaults.k,
        matches=matches,
        summary={
            "source_people_evaluated": len(source_people),
            "target_people_available": len(target_people),
            "approved_mappings_used": len(mappings),
            "match_count": len(matches),
            "average_distance": sum(match.distance for match in matches) / len(matches) if matches else None,
        },
    )
    RUN_DIR.mkdir(parents=True, exist_ok=True)
    (RUN_DIR / f"{result.run_id}.json").write_text(
        result.model_dump_json(indent=2, exclude_none=True, ensure_ascii=False),
        encoding="utf-8",
    )
    state.last_run = result
    save_config(workspace_config, "Ran weighted kNN matching")
    ui.notify(f"Created {len(matches):,} matches", type="positive")
    body_panel.refresh()


def run_live_individual_match() -> None:
    ensure_live_state_defaults()
    source_study_id = state.live_source_study_id
    target_study_id = opposite_config_study(source_study_id)
    source_person = get_person(source_study_id, state.live_source_person_id)
    if not source_study_id or not target_study_id or not source_person:
        ui.notify("Choose a source person from one of the config studies", type="warning")
        return
    if not active_mappings():
        ui.notify("Add at least one approved mapping first", type="warning")
        return
    state.live_matches = find_nearest_matches(source_person, source_study_id, target_study_id, int(state.live_k or 1))
    ui.notify(f"Found {len(state.live_matches)} live matches", type="positive")
    body_panel.refresh()


def run_live_estimate() -> None:
    ensure_live_state_defaults()
    source_study_id = state.estimate_source_study_id
    target_study_id = opposite_config_study(source_study_id)
    source_person = get_person(source_study_id, state.estimate_source_person_id)
    if not source_study_id or not target_study_id or not source_person:
        ui.notify("Choose a source person from one of the config studies", type="warning")
        return
    if not state.estimate_question_id:
        ui.notify("Choose a variable from the opposite study to estimate", type="warning")
        return
    if not active_mappings():
        ui.notify("Add at least one approved mapping first", type="warning")
        return
    matches = find_nearest_matches(source_person, source_study_id, target_study_id, int(state.estimate_k or 1))
    state.estimate_result = {
        "source_study_id": source_study_id,
        "target_study_id": target_study_id,
        "source_person_id": source_person["id"],
        "question_id": state.estimate_question_id,
        "matches": matches,
        "estimate": estimate_from_neighbor_values(matches, target_study_id, state.estimate_question_id),
    }
    ui.notify("Estimated value from live matches", type="positive")
    body_panel.refresh()


def run_validation_estimate() -> None:
    ensure_live_state_defaults()
    source_study_id = state.validation_source_study_id
    target_study_id = opposite_config_study(source_study_id)
    heldout_question_id = state.validation_question_id
    mapping = validation_mapping_for_question(source_study_id, heldout_question_id)
    if not source_study_id or not target_study_id or not mapping:
        ui.notify("Choose a one-to-one mapped variable for validation", type="warning")
        return

    if mapping.left_study_id == source_study_id:
        actual_question_id = mapping.left_inputs[0].question_id
        counterpart_question_id = mapping.right_inputs[0].question_id
    else:
        actual_question_id = mapping.right_inputs[0].question_id
        counterpart_question_id = mapping.left_inputs[0].question_id

    if state.validation_scope == "dataset":
        population = run_validation_population(
            source_study_id,
            target_study_id,
            mapping,
            actual_question_id,
            counterpart_question_id,
            int(state.validation_k or 1),
        )
        state.validation_result = {
            "scope": "dataset",
            "source_study_id": source_study_id,
            "target_study_id": target_study_id,
            "question_id": actual_question_id,
            "counterpart_question_id": counterpart_question_id,
            "heldout_mapping": mapping.model_dump(),
            "summary": population["summary"],
            "cases": population["cases"],
        }
        ui.notify(f"Validated {population['summary'].get('cases_evaluated', 0)} people", type="positive")
        body_panel.refresh()
        return

    source_person = get_person(source_study_id, state.validation_source_person_id)
    if not source_person:
        ui.notify("Choose a person from one of the config studies", type="warning")
        return

    case = validation_case_result(
        source_person,
        source_study_id,
        target_study_id,
        mapping,
        actual_question_id,
        counterpart_question_id,
        int(state.validation_k or 1),
    )
    if case is None:
        ui.notify("That person does not have a value for the held-out variable", type="warning")
        return

    state.validation_result = {
        "scope": "person",
        "source_study_id": source_study_id,
        "target_study_id": target_study_id,
        "question_id": actual_question_id,
        "counterpart_question_id": counterpart_question_id,
        "heldout_mapping": mapping.model_dump(),
        "matches": case["matches"],
        "estimate": case["estimate"],
        "comparison": case["comparison"],
        "source_person_id": case["source_person_id"],
        "source_person_label": case["source_person_label"],
    }
    ui.notify("Validation estimate computed", type="positive")
    body_panel.refresh()


def config_left_id() -> str | None:
    return workspace_config.primary_source_study_id


def config_right_id() -> str | None:
    return workspace_config.primary_target_study_id


def config_study_ids() -> list[str]:
    return [study_id for study_id in [config_left_id(), config_right_id()] if study_id]


def opposite_config_study(study_id: str | None) -> str | None:
    for candidate in config_study_ids():
        if candidate != study_id:
            return candidate
    return None


def person_options(study_id: str | None) -> dict[str, str]:
    if not study_id:
        return {}
    options: dict[str, str] = {}
    for person in store.people_by_study.get(study_id, []):
        source_id = person.get("source_person_id")
        label = f"Person {source_id}" if source_id not in (None, "") else person.get("id", "")
        options[person["id"]] = label
    return options


def get_person(study_id: str | None, person_id: str | None) -> dict[str, Any] | None:
    if not study_id or not person_id:
        return None
    for person in store.people_by_study.get(study_id, []):
        if person.get("id") == person_id:
            return person
    return None


def ensure_live_state_defaults() -> None:
    studies = config_study_ids()
    if not studies:
        return
    if state.live_source_study_id not in studies:
        state.live_source_study_id = studies[0]
        state.live_source_person_id = None
        state.live_matches = []
    if state.estimate_source_study_id not in studies:
        state.estimate_source_study_id = studies[0]
        state.estimate_source_person_id = None
        state.estimate_question_id = None
        state.estimate_result = None
    if state.validation_source_study_id not in studies:
        state.validation_source_study_id = studies[0]
        state.validation_source_person_id = None
        state.validation_question_id = None
        state.validation_result = None

    for attr_name, study_id in [
        ("live_source_person_id", state.live_source_study_id),
        ("estimate_source_person_id", state.estimate_source_study_id),
        ("validation_source_person_id", state.validation_source_study_id),
    ]:
        person_id = getattr(state, attr_name)
        if person_id and get_person(study_id, person_id):
            continue
        people = store.people_by_study.get(study_id or "", [])
        setattr(state, attr_name, people[0].get("id") if people else None)


def live_target_question_options() -> dict[str, str]:
    target_study_id = opposite_config_study(state.estimate_source_study_id)
    if not target_study_id:
        return {}
    mapped_question_ids = {
        item.question_id
        for mapping in active_mappings()
        for item in (
            mapping.left_inputs
            if mapping.left_study_id == target_study_id
            else mapping.right_inputs
            if mapping.right_study_id == target_study_id
            else []
        )
    }
    return {
        question_id: label
        for question_id, label in question_options(target_study_id).items()
        if question_id not in mapped_question_ids
    }


def validation_question_options(study_id: str | None) -> dict[str, str]:
    if not study_id:
        return {}
    options: dict[str, str] = {}
    for mapping in active_mappings():
        if mapping.left_study_id == study_id and len(mapping.left_inputs) == 1 and len(mapping.right_inputs) == 1:
            question = store.questions.get(mapping.left_inputs[0].question_id, {})
            options[mapping.left_inputs[0].question_id] = f"{short_text(question.get('wording'), 110)} [{mapping.name}]"
        elif mapping.right_study_id == study_id and len(mapping.left_inputs) == 1 and len(mapping.right_inputs) == 1:
            question = store.questions.get(mapping.right_inputs[0].question_id, {})
            options[mapping.right_inputs[0].question_id] = f"{short_text(question.get('wording'), 110)} [{mapping.name}]"
    return dict(sorted(options.items(), key=lambda item: item[1].lower()))


def validation_mapping_for_question(study_id: str | None, question_id: str | None) -> VariableSetMapping | None:
    if not study_id or not question_id:
        return None
    candidates = [
        mapping
        for mapping in active_mappings()
        if len(mapping.left_inputs) == 1
        and len(mapping.right_inputs) == 1
        and (
            (mapping.left_study_id == study_id and mapping.left_inputs[0].question_id == question_id)
            or (mapping.right_study_id == study_id and mapping.right_inputs[0].question_id == question_id)
        )
    ]
    return candidates[0] if len(candidates) == 1 else None


def validation_case_result(
    source_person: dict[str, Any],
    source_study_id: str,
    target_study_id: str,
    mapping: VariableSetMapping,
    actual_question_id: str,
    counterpart_question_id: str,
    k: int,
) -> dict[str, Any] | None:
    actual_value = selected_question_value(source_person, actual_question_id)
    if actual_value is None:
        return None
    matches = find_nearest_matches(
        source_person,
        source_study_id,
        target_study_id,
        k,
        excluded_mapping_ids={mapping.mapping_id},
    )
    estimate = estimate_from_neighbor_values(matches, target_study_id, counterpart_question_id)
    estimated_value = estimate.get("estimate")
    actual_num = to_float(actual_value)
    estimated_num = to_float(estimated_value)
    comparison: dict[str, Any] = {
        "kind": (store.questions.get(actual_question_id, {}) or {}).get("kind") or "",
        "actual": actual_value,
        "estimate": estimated_value,
        "error": None,
        "exact_match": None,
    }
    if actual_num is not None and estimated_num is not None:
        comparison["error"] = abs(actual_num - estimated_num)
    elif actual_value is not None and estimated_value is not None:
        comparison["exact_match"] = str(actual_value).lower() == str(estimated_value).lower()

    return {
        "source_person_id": source_person["id"],
        "source_person_label": source_person.get("source_person_id") or source_person["id"],
        "actual": actual_value,
        "estimate": estimate,
        "comparison": comparison,
        "matches": matches,
    }


def run_validation_population(
    source_study_id: str,
    target_study_id: str,
    mapping: VariableSetMapping,
    actual_question_id: str,
    counterpart_question_id: str,
    k: int,
) -> dict[str, Any]:
    cases: list[dict[str, Any]] = []
    numeric_errors: list[float] = []
    exact_matches = 0
    exact_total = 0
    estimates_found = 0
    for person in store.people_by_study.get(source_study_id, []):
        case = validation_case_result(
            person,
            source_study_id,
            target_study_id,
            mapping,
            actual_question_id,
            counterpart_question_id,
            k,
        )
        if case is None:
            continue
        estimates_found += 1 if case["estimate"].get("estimate") is not None else 0
        comparison = case["comparison"]
        if comparison.get("error") is not None:
            numeric_errors.append(float(comparison["error"]))
        elif comparison.get("exact_match") is not None:
            exact_total += 1
            if comparison["exact_match"]:
                exact_matches += 1
        cases.append(case)

    summary: dict[str, Any] = {
        "cases_evaluated": len(cases),
        "estimates_found": estimates_found,
    }
    if numeric_errors:
        summary["mean_absolute_error"] = sum(numeric_errors) / len(numeric_errors)
        summary["median_absolute_error"] = median(numeric_errors)
        summary["max_absolute_error"] = max(numeric_errors)
    if exact_total:
        summary["exact_match_rate"] = exact_matches / exact_total
        summary["exact_match_count"] = exact_matches
        summary["exact_match_total"] = exact_total
    return {"cases": cases, "summary": summary}


def find_nearest_matches(
    source_person: dict[str, Any],
    source_study_id: str,
    target_study_id: str,
    k: int,
    excluded_mapping_ids: set[str] | None = None,
) -> list[PersonMatch]:
    excluded_mapping_ids = excluded_mapping_ids or set()
    mappings = [mapping for mapping in active_mappings() if mapping.mapping_id not in excluded_mapping_ids]
    candidates: list[PersonMatch] = []
    for target_person in store.people_by_study.get(target_study_id, []):
        distance, details, matched, missing = compute_match_distance(source_person, target_person, mappings, source_study_id)
        if distance is None:
            continue
        candidates.append(
            PersonMatch(
                source_person_id=source_person["id"],
                target_person_id=target_person["id"],
                distance=distance,
                similarity=1.0 - distance,
                matched_features_count=matched,
                missing_features_count=missing,
                feature_distances=details,
            )
        )
    return sorted(candidates, key=lambda match: match.distance)[:k]


def selected_question_value(person: dict[str, Any], question_id: str | None) -> Any:
    if not question_id:
        return None
    response = person_response_map(person).get(question_id)
    return raw_response_value(response)


def format_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, float):
        return f"{value:.3f}"
    return short_text(value, 120)


def source_target_value_for_mapping(
    person: dict[str, Any],
    mapping: VariableSetMapping,
    source_study_id: str,
) -> Any:
    if mapping.left_study_id == source_study_id:
        inputs = mapping.left_inputs
        transform = mapping.left_transform
    else:
        inputs = mapping.right_inputs
        transform = mapping.right_transform
    values, missing = collect_inputs(person, inputs)
    return None if missing else transform_value(values, transform)


def other_side_value_for_mapping(
    person: dict[str, Any],
    mapping: VariableSetMapping,
    source_study_id: str,
) -> Any:
    if mapping.left_study_id == source_study_id:
        inputs = mapping.right_inputs
        transform = mapping.right_transform
    else:
        inputs = mapping.left_inputs
        transform = mapping.left_transform
    values, missing = collect_inputs(person, inputs)
    return None if missing else transform_value(values, transform)


def summarize_match_row(source_value: Any, target_values: list[Any]) -> str:
    observed = [value for value in target_values if value is not None]
    if not observed:
        return "no observed values"
    numeric_values = [to_float(value) for value in observed]
    if all(value is not None for value in numeric_values):
        nums = [value for value in numeric_values if value is not None]
        if not nums:
            return f"n={len(observed)}"
        parts = [f"n={len(nums)}", f"mean={sum(nums) / len(nums):.3f}", f"min={min(nums):.3f}", f"max={max(nums):.3f}"]
        source_num = to_float(source_value)
        if source_num is not None:
            parts.append(f"source-mean={abs(source_num - (sum(nums) / len(nums))):.3f}")
        return " · ".join(parts)
    labels = [str(value) for value in observed]
    counts = Counter(labels)
    best_label, best_count = counts.most_common(1)[0]
    return f"n={len(labels)} · mode={short_text(best_label, 40)} · share={best_count / len(labels):.3f}"


def estimate_from_neighbor_values(matches: list[PersonMatch], target_study_id: str, question_id: str) -> dict[str, Any]:
    question = store.questions.get(question_id, {})
    kind = question.get("kind") or ""
    observations: list[dict[str, Any]] = []
    for match in matches:
        person = get_person(target_study_id, match.target_person_id)
        if not person:
            continue
        value = selected_question_value(person, question_id)
        if value is None:
            continue
        weight = max(match.similarity, 0.001)
        observations.append(
            {
                "person_id": match.target_person_id,
                "value": value,
                "display": short_text(value, 140),
                "weight": weight,
                "distance": match.distance,
            }
        )

    if not observations:
        return {"kind": kind, "estimate": None, "method": "no observed neighbor values", "observations": []}

    numeric_values = [(to_float(item["value"]), item["weight"]) for item in observations]
    numeric_values = [(value, weight) for value, weight in numeric_values if value is not None]
    if kind in {"numeric", "ordinal", "likert"} and numeric_values:
        total_weight = sum(weight for _, weight in numeric_values)
        estimate = sum(value * weight for value, weight in numeric_values) / total_weight if total_weight else None
        return {
            "kind": kind,
            "estimate": estimate,
            "method": "similarity-weighted mean",
            "observations": observations,
        }

    weighted_counts: dict[str, float] = {}
    raw_by_label: dict[str, Any] = {}
    for item in observations:
        label = str(item["value"])
        weighted_counts[label] = weighted_counts.get(label, 0.0) + item["weight"]
        raw_by_label[label] = item["value"]
    best_label = max(weighted_counts.items(), key=lambda item: item[1])[0]
    return {
        "kind": kind,
        "estimate": raw_by_label[best_label],
        "method": "similarity-weighted vote" if kind in {"categorical", "binary"} else "nearest-neighbor value summary",
        "observations": observations,
        "weighted_votes": weighted_counts,
    }


def config_header() -> None:
    with ui.row().classes("w-full items-center justify-between gap-3"):
        with ui.column().classes("gap-0"):
            ui.label(workspace_config.name).classes("text-lg font-semibold text-slate-950")
            ui.label(f"{study_name(config_left_id())} ↔ {study_name(config_right_id())}").classes("text-sm text-slate-600")
        ui.badge(workspace_config.config_id, color="blue-grey")


@ui.refreshable
def populations_panel() -> None:
    with ui.row().classes("w-full h-full gap-0 overflow-hidden"):
        with ui.column().classes("w-72 h-full bg-white border-r border-slate-200 p-4 gap-4 overflow-y-auto"):
            for study in store.study_summaries:
                selected = study.id == state.selected_study_id
                with ui.button(on_click=lambda sid=study.id: select_study(sid)).props("flat no-caps align=left").classes(
                    "w-full justify-start px-3 py-2 text-left rounded-md "
                    + ("bg-slate-900 text-white" if selected else "text-slate-700 hover:bg-slate-100")
                ):
                    with ui.column().classes("gap-0 items-start w-full"):
                        ui.label(study.name).classes("text-sm font-medium leading-tight")
                        ui.label(f"{study.person_count:,} people · {study.question_count:,} questions").classes("text-xs opacity-70")
        with ui.column().classes("w-96 h-full bg-slate-50 border-r border-slate-200 p-4 gap-3 overflow-y-auto"):
            ui.input(
                placeholder="Find person",
                value=state.person_query,
                on_change=lambda event: (setattr(state, "person_query", event.value), body_panel.refresh()),
            ).props("clearable dense outlined").classes("w-full")
            people = selected_people()
            max_page = max((len(people) - 1) // PAGE_SIZE, 0)
            start = state.page * PAGE_SIZE
            with ui.row().classes("w-full items-center justify-between gap-2"):
                ui.label(f"{len(people):,} people").classes("text-sm font-medium text-slate-700")
                with ui.row().classes("gap-1 items-center"):
                    ui.button(icon="chevron_left", on_click=lambda: page_delta(-1)).props("flat dense round")
                    ui.label(f"{state.page + 1} / {max_page + 1}").classes("text-xs text-slate-500")
                    ui.button(icon="chevron_right", on_click=lambda: page_delta(1)).props("flat dense round")
            for person in people[start : start + PAGE_SIZE]:
                source_id = person.get("source_person_id")
                title = f"Person {source_id}" if source_id not in (None, "") else person.get("id", "")
                ui.button(
                    f"{title}\n{len(person.get('responses', []))} responses",
                    on_click=lambda pid=person["id"]: select_person(pid),
                ).props("flat no-caps align=left").classes("w-full justify-start text-left")
        with ui.column().classes("flex-1 h-full p-5 gap-3 overflow-y-auto"):
            person = selected_person()
            if not person:
                ui.label("No person selected")
                return
            ui.label(f"Person {person.get('source_person_id')}").classes("text-xl font-semibold")
            query = state.response_query.strip().lower()
            rows = []
            for response in person.get("responses", []):
                question = store.questions.get(response.get("question_id"), {})
                value = display_value(response.get("value"))
                wording = question.get("wording", "")
                if query and query not in f"{wording} {value} {question.get('kind')} {question.get('role')}".lower():
                    continue
                rows.append({"question": short_text(wording, 130), "value": short_text(value, 80), "kind": question.get("kind", ""), "role": question.get("role", "")})
            ui.input(
                placeholder="Filter table",
                value=state.response_query,
                on_change=lambda event: (setattr(state, "response_query", event.value), body_panel.refresh()),
            ).props("clearable dense outlined").classes("w-full max-w-xl")
            ui.table(
                columns=[
                    {"name": "question", "label": "Question", "field": "question", "align": "left"},
                    {"name": "value", "label": "Value", "field": "value", "align": "left"},
                    {"name": "kind", "label": "Kind", "field": "kind", "align": "left"},
                    {"name": "role", "label": "Role", "field": "role", "align": "left"},
                ],
                rows=rows,
                pagination=15,
            ).classes("w-full").props("flat bordered dense wrap-cells")


def questions_for_selected_study() -> list[dict[str, Any]]:
    study_id = state.selected_question_study_id
    if not study_id:
        return []
    query = state.question_filter.strip().lower()
    rows = []
    for question in store.questions_by_study.get(study_id, []):
        wording = question.get("wording", "")
        short_name = question.get("short_name", "")
        kind = question.get("kind", "")
        role = question.get("role", "")
        scale = question.get("scale") or {}
        scale_text = ""
        if isinstance(scale, dict):
            min_value = scale.get("min_value")
            max_value = scale.get("max_value")
            if min_value is not None or max_value is not None:
                scale_text = f"{min_value if min_value is not None else '?'}-{max_value if max_value is not None else '?'}"
            elif scale.get("raw_description"):
                scale_text = str(scale.get("raw_description"))
        searchable = f"{wording} {short_name} {kind} {role} {scale_text}".lower()
        if query and query not in searchable:
            continue
        rows.append(
            {
                "id": question.get("id", ""),
                "short_name": short_text(short_name or question.get("id", ""), 80),
                "wording": short_text(wording, 140),
                "kind": kind,
                "role": role,
                "scale": short_text(scale_text, 40),
            }
        )
    return rows


@ui.refreshable
def questions_panel() -> None:
    with ui.row().classes("w-full h-full gap-0 overflow-hidden"):
        with ui.column().classes("w-72 h-full bg-white border-r border-slate-200 p-4 gap-4 overflow-y-auto"):
            for study_id, label in question_study_options().items():
                selected = study_id == state.selected_question_study_id
                with ui.button(on_click=lambda sid=study_id: select_question_study(sid)).props("flat no-caps align=left").classes(
                    "w-full justify-start px-3 py-2 text-left rounded-md "
                    + ("bg-slate-900 text-white" if selected else "text-slate-700 hover:bg-slate-100")
                ):
                    with ui.column().classes("gap-0 items-start w-full"):
                        ui.label(label).classes("text-sm font-medium leading-tight")
                        ui.label(f"{len(store.questions_by_study.get(study_id, [])):,} questions").classes("text-xs opacity-70")
        with ui.column().classes("flex-1 h-full p-5 gap-3 overflow-y-auto"):
            study_id = state.selected_question_study_id
            ui.label(f"Questions for {study_name(study_id)}").classes("text-xl font-semibold")
            ui.input(
                placeholder="Filter questions",
                value=state.question_filter,
                on_change=lambda event: (setattr(state, "question_filter", event.value), body_panel.refresh()),
            ).props("clearable dense outlined").classes("w-full max-w-2xl")
            rows = questions_for_selected_study()
            ui.label(f"{len(rows):,} questions shown").classes("text-sm text-slate-600")
            ui.table(
                columns=[
                    {"name": "short_name", "label": "Short Name", "field": "short_name", "align": "left"},
                    {"name": "wording", "label": "Question", "field": "wording", "align": "left"},
                    {"name": "kind", "label": "Type", "field": "kind", "align": "left"},
                    {"name": "role", "label": "Role", "field": "role", "align": "left"},
                    {"name": "scale", "label": "Scale", "field": "scale", "align": "left"},
                ],
                rows=rows,
                row_key="id",
                pagination=25,
            ).classes("w-full").props("flat bordered dense wrap-cells")


@ui.refreshable
def config_panel() -> None:
    ui.label("Configurations").classes("text-xl font-semibold text-slate-950")
    ui.select(
        config_options(),
        label="Active config",
        value=workspace_config.config_id,
        on_change=lambda event: load_workspace_config(event.value),
    ).props("outlined dense").classes("w-full max-w-3xl")
    config_header()
    ui.input("Name", value=workspace_config.name, on_change=lambda event: setattr(workspace_config, "name", event.value)).props("outlined dense").classes("w-full max-w-3xl")
    ui.textarea("Description", value=workspace_config.description or "", on_change=lambda event: setattr(workspace_config, "description", event.value)).props("outlined autogrow").classes("w-full max-w-3xl")
    ui.button("Save configuration", icon="save", on_click=lambda: save_workspace()).props("color=primary")

    ui.separator()
    ui.label("Create New Config").classes("text-lg font-semibold")
    ui.input("Config name", value=state.new_config_name, on_change=lambda event: setattr(state, "new_config_name", event.value)).props("outlined dense").classes("w-full max-w-3xl")
    with ui.row().classes("w-full gap-3"):
        ui.select(study_options(), label="Left study", value=state.new_config_left_id, on_change=lambda event: setattr(state, "new_config_left_id", event.value)).props("outlined dense").classes("w-full max-w-md")
        ui.select(study_options(), label="Right study", value=state.new_config_right_id, on_change=lambda event: setattr(state, "new_config_right_id", event.value)).props("outlined dense").classes("w-full max-w-md")
    ui.button("Create config", icon="add", on_click=create_workspace_from_form).props("color=primary")


def save_workspace() -> None:
    save_config(workspace_config)
    ui.notify("Configuration saved", type="positive")


def input_slots(side: str, question_ids: list[str | None], aliases: list[str], required: list[bool], options: dict[str, str]) -> None:
    for index in range(INPUT_SLOTS):
        with ui.grid(columns="1fr 180px 100px").classes("w-full gap-2 items-end"):
            ui.select(
                options,
                label=f"{side} input {index + 1}",
                value=question_ids[index],
                on_change=lambda event, i=index, ids=question_ids: ids.__setitem__(i, event.value),
            ).props("outlined dense clearable").classes("w-full")
            ui.input(
                "Alias",
                value=aliases[index],
                on_change=lambda event, i=index, values=aliases: values.__setitem__(i, event.value),
            ).props("outlined dense").classes("w-full")
            ui.checkbox(
                "Required",
                value=required[index],
                on_change=lambda event, i=index, values=required: values.__setitem__(i, bool(event.value)),
            )


@ui.refreshable
def mappings_panel() -> None:
    ui.label("Variable-Set Mappings").classes("text-xl font-semibold text-slate-950")
    config_header()
    ui.label("Each mapping stores input sets, left/right transforms, a comparator, weight, and notes.").classes("text-sm text-slate-500")

    with ui.card().classes("w-full rounded-md shadow-none border border-slate-200"):
        ui.label("Add Variable-Set Mapping").classes("text-base font-semibold")
        ui.input("Mapping name", value=state.mapping_name, on_change=lambda event: setattr(state, "mapping_name", event.value)).props("outlined dense").classes("w-full max-w-3xl")
        ui.textarea("Description", value=state.mapping_description, on_change=lambda event: setattr(state, "mapping_description", event.value)).props("outlined autogrow").classes("w-full max-w-3xl")
        with ui.grid(columns="1fr 1fr").classes("w-full gap-4"):
            with ui.column().classes("gap-2"):
                ui.label(f"Left inputs: {study_name(config_left_id())}").classes("font-medium")
                input_slots("Left", state.left_question_ids, state.left_aliases, state.left_required, question_options(config_left_id()))
                ui.select(transform_options(), label="Left transform", value=state.left_transform_kind, on_change=lambda event: setattr(state, "left_transform_kind", event.value)).props("outlined dense").classes("w-full")
                ui.textarea("Left transform parameters JSON", value=state.left_transform_parameters, on_change=lambda event: setattr(state, "left_transform_parameters", event.value)).props("outlined autogrow").classes("w-full")
            with ui.column().classes("gap-2"):
                ui.label(f"Right inputs: {study_name(config_right_id())}").classes("font-medium")
                input_slots("Right", state.right_question_ids, state.right_aliases, state.right_required, question_options(config_right_id()))
                ui.select(transform_options(), label="Right transform", value=state.right_transform_kind, on_change=lambda event: setattr(state, "right_transform_kind", event.value)).props("outlined dense").classes("w-full")
                ui.textarea("Right transform parameters JSON", value=state.right_transform_parameters, on_change=lambda event: setattr(state, "right_transform_parameters", event.value)).props("outlined autogrow").classes("w-full")
        with ui.grid(columns="1fr 1fr 180px").classes("w-full gap-3 items-end"):
            ui.select(comparator_options(), label="Comparator", value=state.comparator_kind, on_change=lambda event: setattr(state, "comparator_kind", event.value)).props("outlined dense").classes("w-full")
            ui.select(output_kind_options(), label="Comparable output kind", value=state.output_kind, on_change=lambda event: setattr(state, "output_kind", event.value)).props("outlined dense").classes("w-full")
            ui.number("Weight", value=state.mapping_weight, min=0, on_change=lambda event: setattr(state, "mapping_weight", float(event.value or 1.0))).props("outlined dense")
        ui.textarea("Comparator parameters JSON", value=state.comparator_parameters, on_change=lambda event: setattr(state, "comparator_parameters", event.value)).props("outlined autogrow").classes("w-full")
        ui.textarea("Notes", value=state.mapping_notes, on_change=lambda event: setattr(state, "mapping_notes", event.value)).props("outlined autogrow").classes("w-full")
        with ui.row().classes("gap-2"):
            ui.button("Save variable-set mapping", icon="check", on_click=save_variable_set_mapping).props("color=primary")
            ui.button("Clear form", icon="restart_alt", on_click=lambda: (reset_mapping_form(), body_panel.refresh())).props("outline")

    rows = []
    for mapping in workspace_config.variable_set_mappings:
        rows.append(
            {
                "id": mapping.mapping_id,
                "name": mapping.name,
                "left": ", ".join(item.alias for item in mapping.left_inputs),
                "right": ", ".join(item.alias for item in mapping.right_inputs),
                "transforms": f"{mapping.left_transform.kind} / {mapping.right_transform.kind}",
                "comparator": mapping.comparator.kind,
                "weight": mapping.weight,
                "status": mapping.status,
            }
        )
    table = ui.table(
        columns=[
            {"name": "name", "label": "Name", "field": "name", "align": "left"},
            {"name": "left", "label": "Left Inputs", "field": "left", "align": "left"},
            {"name": "right", "label": "Right Inputs", "field": "right", "align": "left"},
            {"name": "transforms", "label": "Transforms", "field": "transforms", "align": "left"},
            {"name": "comparator", "label": "Comparator", "field": "comparator", "align": "left"},
            {"name": "weight", "label": "Weight", "field": "weight", "align": "right"},
            {"name": "status", "label": "Status", "field": "status", "align": "left"},
        ],
        rows=rows,
        row_key="id",
        pagination=10,
    ).classes("w-full").props("flat bordered dense wrap-cells")


@ui.refreshable
def matching_panel() -> None:
    ui.label("Matching").classes("text-xl font-semibold")
    config_header()
    with ui.row().classes("gap-3 items-end"):
        ui.number("k nearest neighbors", value=workspace_config.matching_defaults.k, min=1, max=50, on_change=lambda event: setattr(workspace_config.matching_defaults, "k", int(event.value or 1))).props("outlined dense").classes("w-48")
        ui.number("Source people limit", value=state.match_limit, min=1, max=500, on_change=lambda event: setattr(state, "match_limit", int(event.value or 1))).props("outlined dense").classes("w-48")
        ui.button("Run matching", icon="play_arrow", on_click=run_matching).props("color=primary")
    ui.label(f"{len(active_mappings())} approved variable-set mappings available").classes("text-sm text-slate-600")
    if state.last_run:
        result = state.last_run
        avg = result.summary.get("average_distance")
        with ui.row().classes("gap-2 flex-wrap"):
            ui.badge(f"{result.summary.get('match_count', 0):,} matches", color="green")
            ui.badge(f"{result.summary.get('approved_mappings_used', 0)} mappings", color="indigo")
            if avg is not None:
                ui.badge(f"avg distance {avg:.3f}", color="blue-grey")


@ui.refreshable
def individual_matching_panel() -> None:
    ensure_live_state_defaults()
    ui.label("Individual Matching").classes("text-xl font-semibold")
    config_header()
    ui.label("Live nearest-neighbor matching for one selected person. Results are not saved.").classes("text-sm text-slate-600")

    studies = config_study_ids()
    source_options = {study_id: study_name(study_id) for study_id in studies}
    target_study_id = opposite_config_study(state.live_source_study_id)
    with ui.row().classes("gap-3 items-end flex-wrap"):
        ui.select(
            source_options,
            label="Source study",
            value=state.live_source_study_id,
            on_change=lambda event: (
                setattr(state, "live_source_study_id", event.value),
                setattr(state, "live_source_person_id", None),
                setattr(state, "live_matches", []),
                ensure_live_state_defaults(),
                body_panel.refresh(),
            ),
        ).props("outlined dense").classes("w-80")
        ui.select(
            person_options(state.live_source_study_id),
            label="Source person",
            value=state.live_source_person_id,
            on_change=lambda event: (setattr(state, "live_source_person_id", event.value), setattr(state, "live_matches", [])),
        ).props("outlined dense").classes("w-72")
        ui.number(
            "Neighbors",
            value=state.live_k,
            min=1,
            max=50,
            on_change=lambda event: setattr(state, "live_k", int(event.value or 1)),
        ).props("outlined dense").classes("w-36")
        ui.button("Find matches", icon="search", on_click=run_live_individual_match).props("color=primary")

    ui.label(f"Target study: {study_name(target_study_id)}").classes("text-sm text-slate-600")
    ui.label(f"{len(active_mappings())} approved mappings will be used").classes("text-sm text-slate-600")

    source_person = get_person(state.live_source_study_id, state.live_source_person_id)
    if not source_person:
        ui.label("Choose a source person and find matches to inspect the comparison matrix.").classes("text-sm text-slate-500")
        return

    if not state.live_matches:
        ui.label("Choose a person and find matches to inspect nearest neighbors.").classes("text-sm text-slate-500")
        return

    active_rows = active_mappings()
    match_columns = []
    for index, match in enumerate(state.live_matches, start=1):
        target_person = get_person(target_study_id, match.target_person_id)
        label = target_person.get("source_person_id") if target_person else match.target_person_id
        match_columns.append(
            {
                "name": f"match_{index}",
                "label": f"{label}\n(sim {match.similarity:.3f})",
                "field": f"match_{index}",
                "align": "left",
            }
        )

    rows = []
    for mapping in active_rows:
        source_value = source_target_value_for_mapping(source_person, mapping, state.live_source_study_id)
        match_values: list[Any] = []
        for match in state.live_matches:
            detail = next((item for item in match.feature_distances if item.mapping_id == mapping.mapping_id), None)
            match_values.append(detail.target_value if detail else None)
        rows.append(
            {
                "variable": mapping.name,
                "source": format_value(source_value),
                "summary": summarize_match_row(source_value, match_values),
                **{f"match_{index}": format_value(value) for index, value in enumerate(match_values, start=1)},
            }
        )

    ui.table(
        columns=[
            {"name": "variable", "label": "Variable", "field": "variable", "align": "left"},
            {"name": "source", "label": "Person being matched", "field": "source", "align": "left"},
            {"name": "summary", "label": "Summary stats", "field": "summary", "align": "left"},
            *match_columns,
        ],
        rows=rows,
        pagination=20,
    ).classes("w-full").props("flat bordered dense wrap-cells")


@ui.refreshable
def estimation_panel() -> None:
    ensure_live_state_defaults()
    ui.label("Estimate / Validate").classes("text-xl font-semibold")
    config_header()
    ui.label("Use live matching either to estimate a missing variable or to validate a known one by holding it out. Results are not saved.").classes("text-sm text-slate-600")

    studies = config_study_ids()
    source_options = {study_id: study_name(study_id) for study_id in studies}
    mode_options = {
        "estimate_missing": "Estimate missing variable",
        "validate_known": "Validate known variable",
    }

    ui.select(
        mode_options,
        label="Mode",
        value=state.estimation_mode,
        on_change=lambda event: (
            setattr(state, "estimation_mode", event.value),
            setattr(state, "estimate_result", None),
            setattr(state, "validation_result", None),
            body_panel.refresh(),
        ),
    ).props("outlined dense").classes("w-full max-w-md")

    if state.estimation_mode == "validate_known":
        validation_options = validation_question_options(state.validation_source_study_id)
        if state.validation_question_id not in validation_options:
            state.validation_question_id = next(iter(validation_options), None)
        target_study_id = opposite_config_study(state.validation_source_study_id)
        ui.select(
            {"person": "Single person", "dataset": "Whole dataset"},
            label="Validation scope",
            value=state.validation_scope,
            on_change=lambda event: (
                setattr(state, "validation_scope", event.value),
                setattr(state, "validation_result", None),
                body_panel.refresh(),
            ),
        ).props("outlined dense").classes("w-full max-w-md")
        with ui.row().classes("gap-3 items-end flex-wrap"):
            ui.select(
                source_options,
                label="Person's study",
                value=state.validation_source_study_id,
                on_change=lambda event: (
                    setattr(state, "validation_source_study_id", event.value),
                    setattr(state, "validation_source_person_id", None),
                    setattr(state, "validation_question_id", None),
                    setattr(state, "validation_result", None),
                    ensure_live_state_defaults(),
                    body_panel.refresh(),
                ),
            ).props("outlined dense").classes("w-80")
            if state.validation_scope == "person":
                ui.select(
                    person_options(state.validation_source_study_id),
                    label="Person",
                    value=state.validation_source_person_id,
                    on_change=lambda event: (setattr(state, "validation_source_person_id", event.value), setattr(state, "validation_result", None)),
                ).props("outlined dense").classes("w-72")
            ui.number(
                "Neighbors",
                value=state.validation_k,
                min=1,
                max=50,
                on_change=lambda event: setattr(state, "validation_k", int(event.value or 1)),
            ).props("outlined dense").classes("w-36")
        ui.select(
            validation_options,
            label=f"Known variable to validate from {study_name(state.validation_source_study_id)}",
            value=state.validation_question_id,
            on_change=lambda event: (setattr(state, "validation_question_id", event.value), setattr(state, "validation_result", None)),
        ).props("outlined dense").classes("w-full max-w-4xl")
        ui.button("Validate value", icon="rule", on_click=run_validation_estimate).props("color=primary")

        if not state.validation_result:
            if state.validation_scope == "dataset":
                ui.label("Choose one of the source study's one-to-one mapped variables and validate it across the whole dataset.").classes("text-sm text-slate-500")
            else:
                ui.label("Choose one of the person's own one-to-one mapped variables and hold it out for validation.").classes("text-sm text-slate-500")
            return

        result = state.validation_result
        heldout = result["heldout_mapping"]
        question = store.questions.get(result["question_id"], {})
        with ui.card().classes("w-full rounded-md shadow-none border border-slate-200"):
            ui.label(short_text(question.get("wording"), 180)).classes("text-sm font-medium text-slate-800")
            ui.label(f"Held-out mapping: {heldout.get('name')}").classes("text-xs text-slate-500")
            if result.get("scope") == "dataset":
                summary = result["summary"]
                ui.label(
                    f"Validated {summary.get('cases_evaluated', 0)} people · estimates found {summary.get('estimates_found', 0)}"
                ).classes("text-base font-semibold text-slate-950")
                metrics = []
                if summary.get("mean_absolute_error") is not None:
                    metrics.append(f"MAE {summary['mean_absolute_error']:.3f}")
                if summary.get("median_absolute_error") is not None:
                    metrics.append(f"median AE {summary['median_absolute_error']:.3f}")
                if summary.get("exact_match_rate") is not None:
                    metrics.append(f"accuracy {summary['exact_match_rate']:.3f}")
                ui.label(" · ".join(metrics) if metrics else "No comparable values found").classes("text-sm text-slate-600")
            else:
                estimate = result["estimate"]
                comparison = result["comparison"]
                ui.label(f"Method: {estimate.get('method')}").classes("text-xs text-slate-500")
                actual = comparison.get("actual")
                predicted = comparison.get("estimate")
                if isinstance(actual, float) or isinstance(predicted, float):
                    ui.label(
                        f"Actual: {actual if actual is not None else 'n/a'} | Estimated: {predicted if predicted is not None else 'n/a'} | Error: {comparison.get('error') if comparison.get('error') is not None else 'n/a'}"
                    ).classes("text-base font-semibold text-slate-950")
                else:
                    ui.label(
                        f"Actual: {short_text(actual, 120) if actual is not None else 'n/a'} | Estimated: {short_text(predicted, 120) if predicted is not None else 'n/a'} | Exact match: {comparison.get('exact_match')}"
                    ).classes("text-base font-semibold text-slate-950")

        case_rows = []
        for case in result.get("cases", [result]):
            comparison = case.get("comparison", {})
            estimate_value = case.get("estimate", {}).get("estimate") if isinstance(case.get("estimate"), dict) else case.get("estimate")
            case_rows.append(
                {
                    "person": case.get("source_person_label", ""),
                    "actual": short_text(comparison.get("actual"), 120),
                    "estimated": short_text(estimate_value, 120),
                    "error": "" if comparison.get("error") is None else f"{comparison.get('error'):.3f}",
                    "exact": "" if comparison.get("exact_match") is None else str(comparison.get("exact_match")),
                }
            )
        ui.table(
            columns=[
                {"name": "person", "label": "Person", "field": "person", "align": "left"},
                {"name": "actual", "label": "Actual", "field": "actual", "align": "left"},
                {"name": "estimated", "label": "Estimated", "field": "estimated", "align": "left"},
                {"name": "error", "label": "Error", "field": "error", "align": "right"},
                {"name": "exact", "label": "Exact Match", "field": "exact", "align": "left"},
            ],
            rows=case_rows,
            pagination=15,
        ).classes("w-full").props("flat bordered dense wrap-cells")
        return

    target_study_id = opposite_config_study(state.estimate_source_study_id)
    target_question_options = live_target_question_options()
    if state.estimate_question_id not in target_question_options:
        state.estimate_question_id = next(iter(target_question_options), None)

    with ui.row().classes("gap-3 items-end flex-wrap"):
        ui.select(
            source_options,
            label="Person's study",
            value=state.estimate_source_study_id,
            on_change=lambda event: (
                setattr(state, "estimate_source_study_id", event.value),
                setattr(state, "estimate_source_person_id", None),
                setattr(state, "estimate_question_id", None),
                setattr(state, "estimate_result", None),
                ensure_live_state_defaults(),
                body_panel.refresh(),
            ),
        ).props("outlined dense").classes("w-80")
        ui.select(
            person_options(state.estimate_source_study_id),
            label="Person",
            value=state.estimate_source_person_id,
            on_change=lambda event: (setattr(state, "estimate_source_person_id", event.value), setattr(state, "estimate_result", None)),
        ).props("outlined dense").classes("w-72")
        ui.number(
            "Neighbors",
            value=state.estimate_k,
            min=1,
            max=50,
            on_change=lambda event: setattr(state, "estimate_k", int(event.value or 1)),
        ).props("outlined dense").classes("w-36")

    ui.select(
        target_question_options,
        label=f"Variable to estimate from {study_name(target_study_id)}",
        value=state.estimate_question_id,
        on_change=lambda event: (setattr(state, "estimate_question_id", event.value), setattr(state, "estimate_result", None)),
    ).props("outlined dense").classes("w-full max-w-4xl")
    ui.button("Estimate value", icon="functions", on_click=run_live_estimate).props("color=primary")

    if not state.estimate_result:
        ui.label("Choose a target variable and estimate it from the selected person's nearest neighbors.").classes("text-sm text-slate-500")
        return

    result = state.estimate_result
    estimate = result["estimate"]
    question = store.questions.get(result["question_id"], {})
    with ui.card().classes("w-full rounded-md shadow-none border border-slate-200"):
        ui.label(short_text(question.get("wording"), 180)).classes("text-sm font-medium text-slate-800")
        ui.label(f"Method: {estimate.get('method')}").classes("text-xs text-slate-500")
        value = estimate.get("estimate")
        if isinstance(value, float):
            ui.label(f"Estimated value: {value:.3f}").classes("text-2xl font-semibold text-slate-950")
        else:
            ui.label(f"Estimated value: {short_text(value, 160) if value is not None else 'No estimate'}").classes("text-2xl font-semibold text-slate-950")

    match_rows = []
    for rank, match in enumerate(result["matches"], start=1):
        person = get_person(result["target_study_id"], match.target_person_id)
        observed = selected_question_value(person, result["question_id"]) if person else None
        match_rows.append(
            {
                "rank": rank,
                "person": person.get("source_person_id") if person else match.target_person_id,
                "distance": f"{match.distance:.3f}",
                "similarity": f"{match.similarity:.3f}",
                "observed": short_text(observed, 120),
            }
        )
    ui.table(
        columns=[
            {"name": "rank", "label": "#", "field": "rank", "align": "right"},
            {"name": "person", "label": "Matched Person", "field": "person", "align": "left"},
            {"name": "distance", "label": "Distance", "field": "distance", "align": "right"},
            {"name": "similarity", "label": "Similarity", "field": "similarity", "align": "right"},
            {"name": "observed", "label": "Observed Target Value", "field": "observed", "align": "left"},
        ],
        rows=match_rows,
        pagination=10,
    ).classes("w-full").props("flat bordered dense wrap-cells")


@ui.refreshable
def notes_panel() -> None:
    ui.label("Notes").classes("text-xl font-semibold")
    config_header()
    ui.textarea("Add note", value=state.note_text, on_change=lambda event: setattr(state, "note_text", event.value)).props("outlined autogrow").classes("w-full max-w-3xl")
    ui.button("Add note", icon="note_add", on_click=add_note).props("color=primary")
    for note in reversed(workspace_config.notes):
        with ui.card().classes("w-full rounded-md shadow-none border border-slate-200"):
            ui.label(note.text).classes("text-sm text-slate-900 whitespace-pre-wrap")
            ui.label(note.updated_at.strftime("%Y-%m-%d %H:%M")).classes("text-xs text-slate-500")


@ui.refreshable
def body_panel() -> None:
    if state.active_view == "studies":
        populations_panel()
        return
    if state.active_view == "questions":
        questions_panel()
        return
    with ui.column().classes("w-full h-full p-5 gap-3 overflow-y-auto"):
        if state.active_view == "config":
            config_panel()
        elif state.active_view == "mappings":
            mappings_panel()
        elif state.active_view == "matching":
            matching_panel()
        elif state.active_view == "individual_matching":
            individual_matching_panel()
        elif state.active_view == "estimation":
            estimation_panel()
        elif state.active_view == "notes":
            notes_panel()


ui.add_head_html(
    """
    <style>
      body { background: #f8fafc; }
      .nicegui-content { padding: 0; }
      .q-table th { font-weight: 700; color: #334155; }
      .q-table td { vertical-align: top; }
    </style>
    """
)

with ui.row().classes("w-full h-screen gap-0 overflow-hidden"):
    with ui.column().classes("w-72 h-full bg-white border-r border-slate-200 p-4 gap-4 overflow-y-auto"):
        ui.label("Population Data").classes("text-lg font-semibold text-slate-950")
        ui.label(f"{store.metadata.get('person_count', 0):,} people · {store.metadata.get('question_count', 0):,} questions").classes("text-xs text-slate-500")
        for view, label, icon in [
            ("studies", "Studies - populations", "groups"),
            ("questions", "Studies - questions", "help"),
            ("config", "Config", "settings"),
            ("mappings", "Mappings", "hub"),
            ("matching", "Matching", "compare_arrows"),
            ("individual_matching", "Individual Match", "person_search"),
            ("estimation", "Estimate Value", "functions"),
            ("notes", "Notes", "notes"),
        ]:
            ui.button(label, icon=icon, on_click=lambda selected=view: set_active_view(selected)).props("flat no-caps align=left").classes("w-full justify-start")
    with ui.column().classes("flex-1 h-full gap-0 overflow-hidden"):
        body_panel()


if __name__ == "__main__":
    ui.run(title="Population Data Navigator", host="127.0.0.1", port=8080, reload=False)
