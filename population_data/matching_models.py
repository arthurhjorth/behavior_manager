from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex[:12]}"


class MappingStatus(StrEnum):
    DRAFT = "draft"
    APPROVED = "approved"
    REJECTED = "rejected"
    DISABLED = "disabled"


class TransformKind(StrEnum):
    IDENTITY = "identity"
    IDENTITY_NUMERIC = "identity_numeric"
    IDENTITY_CATEGORY = "identity_category"
    NORMALIZE_MINMAX = "normalize_minmax"
    CATEGORY_TO_INTERVAL = "category_to_interval"
    CATEGORY_RECODE = "category_recode"
    BINARY_RECODE = "binary_recode"
    MULTI_INPUT_VECTOR = "multi_input_vector"
    DERIVE_ADULTS_CHILDREN = "derive_adults_children"
    COLLAPSE_HOUSEHOLD_AGE_COUNTS = "collapse_household_age_counts"
    CUSTOM = "custom"


class ComparatorKind(StrEnum):
    SCALED_ABSOLUTE_DISTANCE = "scaled_absolute_distance"
    EXACT_MATCH = "exact_match"
    BINARY_MISMATCH = "binary_mismatch"
    JACCARD_DISTANCE = "jaccard_distance"
    NUMERIC_TO_INTERVAL_DISTANCE = "numeric_to_interval_distance"
    INTERVAL_OVERLAP_DISTANCE = "interval_overlap_distance"
    WEIGHTED_COMPONENT_DISTANCE = "weighted_component_distance"
    CUSTOM = "custom"


class ComparableValueKind(StrEnum):
    NUMBER = "number"
    CATEGORY = "category"
    BOOLEAN = "boolean"
    TEXT = "text"
    LIST = "list"
    INTERVAL = "interval"
    VECTOR = "vector"
    OBJECT = "object"


class MissingPolicy(StrEnum):
    PAIRWISE_IGNORE = "pairwise_ignore"
    PENALIZE = "penalize"
    REQUIRE = "require"


class MatchingMethod(StrEnum):
    WEIGHTED_KNN = "weighted_knn"


class ReplacementPolicy(StrEnum):
    ALLOW_REUSE = "allow_reuse"
    ONE_TO_ONE = "one_to_one"
    CAPPED_REUSE = "capped_reuse"


class MappingInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question_id: str
    alias: str
    required: bool = True


class TransformSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: TransformKind = TransformKind.IDENTITY
    input_aliases: list[str] = Field(default_factory=list)
    output_alias: str = "value"
    parameters: dict[str, Any] = Field(default_factory=dict)
    notes: str | None = None


class ComparatorSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: ComparatorKind = ComparatorKind.EXACT_MATCH
    parameters: dict[str, Any] = Field(default_factory=dict)
    missing_policy: MissingPolicy = MissingPolicy.PAIRWISE_IGNORE
    notes: str | None = None


class VariableSetMapping(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mapping_id: str = Field(default_factory=lambda: new_id("mapping"))
    name: str
    description: str | None = None
    left_study_id: str
    right_study_id: str
    left_inputs: list[MappingInput] = Field(default_factory=list)
    right_inputs: list[MappingInput] = Field(default_factory=list)
    left_transform: TransformSpec = Field(default_factory=TransformSpec)
    right_transform: TransformSpec = Field(default_factory=TransformSpec)
    comparator: ComparatorSpec = Field(default_factory=ComparatorSpec)
    output_kind: ComparableValueKind = ComparableValueKind.NUMBER
    weight: float = Field(default=1.0, ge=0)
    status: MappingStatus = MappingStatus.APPROVED
    notes: str | None = None
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)


class MatchingConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    method: MatchingMethod = MatchingMethod.WEIGHTED_KNN
    k: int = Field(default=5, ge=1)
    source_study_id: str | None = None
    target_study_id: str | None = None
    replacement_policy: ReplacementPolicy = ReplacementPolicy.ALLOW_REUSE
    capped_reuse_limit: int | None = Field(default=None, ge=1)
    caliper: float | None = Field(default=None, ge=0)
    missing_policy: MissingPolicy = MissingPolicy.PAIRWISE_IGNORE
    normalize_weights: bool = True
    random_seed: int = 42
    notes: str | None = None


class DiagnosticsConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    compare_distributions: bool = True
    show_worst_matches: bool = True
    show_feature_contributions: bool = True
    balance_variables: list[str] = Field(default_factory=list)


class AuditEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    timestamp: datetime = Field(default_factory=datetime.now)
    event_type: str
    message: str
    object_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class Note(BaseModel):
    model_config = ConfigDict(extra="forbid")

    note_id: str = Field(default_factory=lambda: new_id("note"))
    text: str
    scope: str = "workspace"
    object_id: str | None = None
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)
    tags: list[str] = Field(default_factory=list)


class FeatureDistance(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mapping_id: str
    mapping_name: str
    distance: float | None = None
    weight: float
    source_value: Any = None
    target_value: Any = None
    missing: bool = False


class PersonMatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_person_id: str
    target_person_id: str
    distance: float
    similarity: float
    matched_features_count: int
    missing_features_count: int
    feature_distances: list[FeatureDistance] = Field(default_factory=list)


class MatchRunResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: str = Field(default_factory=lambda: new_id("run"))
    created_at: datetime = Field(default_factory=datetime.now)
    config_id: str
    source_study_id: str
    target_study_id: str
    method: MatchingMethod
    k: int
    matches: list[PersonMatch] = Field(default_factory=list)
    summary: dict[str, Any] = Field(default_factory=dict)


class MatchingWorkspaceConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = "0.2.0"
    config_id: str = Field(default_factory=lambda: new_id("config"))
    name: str = "Matching workspace"
    description: str | None = None
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)

    dataset_path: str
    dataset_fingerprint: str | None = None
    study_ids: list[str] = Field(default_factory=list)
    primary_source_study_id: str | None = None
    primary_target_study_id: str | None = None

    variable_set_mappings: list[VariableSetMapping] = Field(default_factory=list)
    matching_defaults: MatchingConfig = Field(default_factory=MatchingConfig)
    diagnostics: DiagnosticsConfig = Field(default_factory=DiagnosticsConfig)
    notes: list[Note] = Field(default_factory=list)
    audit_events: list[AuditEvent] = Field(default_factory=list)

    def touch(self) -> None:
        self.updated_at = datetime.now()
