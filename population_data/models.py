from __future__ import annotations

from datetime import date, datetime
from enum import StrEnum
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class DataKind(StrEnum):
    NUMERIC = "numeric"
    ORDINAL = "ordinal"
    LIKERT = "likert"
    SEMANTIC_DIFFERENTIAL = "semantic_differential"
    CATEGORICAL = "categorical"
    BINARY = "binary"
    MULTI_SELECT = "multi_select"
    TEXT = "text"
    DERIVED = "derived"
    EXPERIMENTAL_CONDITION = "experimental_condition"
    ATTENTION_OR_QUALITY = "attention_or_quality"
    DEMOGRAPHIC = "demographic"
    UNKNOWN = "unknown"


class QuestionRole(StrEnum):
    DEMOGRAPHIC = "demographic"
    BELIEF = "belief"
    BEHAVIOR = "behavior"
    PREFERENCE = "preference"
    OUTCOME = "outcome"
    EXPERIMENTAL_CONDITION = "experimental_condition"
    QUALITY_CONTROL = "quality_control"
    DERIVED = "derived"
    METADATA = "metadata"
    UNKNOWN = "unknown"


class ValueKind(StrEnum):
    NUMBER = "number"
    INTEGER = "integer"
    STRING = "string"
    BOOLEAN = "boolean"
    DATE = "date"
    DATETIME = "datetime"
    CATEGORY = "category"
    LIST = "list"
    MISSING = "missing"


class SourceRef(BaseModel):
    model_config = ConfigDict(extra="forbid")

    file_path: str
    sheet_name: str | None = None
    row_index: int | None = Field(default=None, ge=1)
    column_index: int | None = Field(default=None, ge=1)
    column_name: str | None = None


class Study(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    name: str
    source_file: str
    source_sheet: str | None = None
    description: str | None = None
    collected_at: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class Option(BaseModel):
    model_config = ConfigDict(extra="forbid")

    value: Any
    label: str | None = None
    order: int | None = None
    is_missing: bool = False


class Scale(BaseModel):
    model_config = ConfigDict(extra="forbid")

    min_value: float | None = None
    max_value: float | None = None
    min_label: str | None = None
    max_label: str | None = None
    step: float | None = None
    options: list[Option] = Field(default_factory=list)
    raw_description: str | None = None


class QuestionBase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    study_id: str
    kind: DataKind
    wording: str
    source: SourceRef
    short_name: str | None = None
    role: QuestionRole = QuestionRole.UNKNOWN
    constructs: list[str] = Field(default_factory=list)
    scale: Scale | None = None
    missing_codes: list[Any] = Field(default_factory=list)
    reverse_scored: bool = False
    harmonized_variable_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class NumericQuestion(QuestionBase):
    kind: Literal[DataKind.NUMERIC] = DataKind.NUMERIC
    unit: str | None = None


class OrdinalQuestion(QuestionBase):
    kind: Literal[DataKind.ORDINAL] = DataKind.ORDINAL
    ordered: bool = True


class LikertQuestion(OrdinalQuestion):
    kind: Literal[DataKind.LIKERT] = DataKind.LIKERT


class SemanticDifferentialQuestion(OrdinalQuestion):
    kind: Literal[DataKind.SEMANTIC_DIFFERENTIAL] = DataKind.SEMANTIC_DIFFERENTIAL
    left_anchor: str | None = None
    right_anchor: str | None = None


class CategoricalQuestion(QuestionBase):
    kind: Literal[DataKind.CATEGORICAL] = DataKind.CATEGORICAL


class BinaryQuestion(CategoricalQuestion):
    kind: Literal[DataKind.BINARY] = DataKind.BINARY
    true_value: Any | None = None
    false_value: Any | None = None


class ExperimentalConditionQuestion(CategoricalQuestion):
    kind: Literal[DataKind.EXPERIMENTAL_CONDITION] = DataKind.EXPERIMENTAL_CONDITION
    role: QuestionRole = QuestionRole.EXPERIMENTAL_CONDITION


class MultiSelectQuestion(QuestionBase):
    kind: Literal[DataKind.MULTI_SELECT] = DataKind.MULTI_SELECT
    option_question_ids: list[str] = Field(default_factory=list)


class TextQuestion(QuestionBase):
    kind: Literal[DataKind.TEXT] = DataKind.TEXT
    language: str | None = None


class DerivedQuestion(QuestionBase):
    kind: Literal[DataKind.DERIVED] = DataKind.DERIVED
    role: QuestionRole = QuestionRole.DERIVED
    derived_from_question_ids: list[str] = Field(default_factory=list)
    formula: str | None = None


class AttentionOrQualityQuestion(QuestionBase):
    kind: Literal[DataKind.ATTENTION_OR_QUALITY] = DataKind.ATTENTION_OR_QUALITY
    role: QuestionRole = QuestionRole.QUALITY_CONTROL


class DemographicQuestion(QuestionBase):
    kind: Literal[DataKind.DEMOGRAPHIC] = DataKind.DEMOGRAPHIC
    role: QuestionRole = QuestionRole.DEMOGRAPHIC


Question = Annotated[
    NumericQuestion
    | OrdinalQuestion
    | LikertQuestion
    | SemanticDifferentialQuestion
    | CategoricalQuestion
    | BinaryQuestion
    | ExperimentalConditionQuestion
    | MultiSelectQuestion
    | TextQuestion
    | DerivedQuestion
    | AttentionOrQualityQuestion
    | DemographicQuestion,
    Field(discriminator="kind"),
]


class ResponseValue(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: ValueKind
    raw: Any = None
    normalized: Any = None
    label: str | None = None
    is_missing: bool = False


class Response(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question_id: str
    value: ResponseValue
    source: SourceRef
    metadata: dict[str, Any] = Field(default_factory=dict)


class Person(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    study_id: str
    source_person_id: str | int | None = None
    attributes: dict[str, ResponseValue] = Field(default_factory=dict)
    responses: list[Response] = Field(default_factory=list)
    weights: dict[str, float] = Field(default_factory=dict)
    source: SourceRef
    metadata: dict[str, Any] = Field(default_factory=dict)


class PopulationDataset(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = "0.1.0"
    created_at: datetime = Field(default_factory=datetime.now)
    studies: list[Study] = Field(default_factory=list)
    questions: list[Question] = Field(default_factory=list)
    people: list[Person] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


JsonPrimitive = str | int | float | bool | None
JsonValue = JsonPrimitive | list["JsonValue"] | dict[str, "JsonValue"]
