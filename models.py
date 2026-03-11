from abc import ABC, abstractmethod
from datetime import datetime
from enum import Enum
import math
from typing import Any, Callable, Iterator, Optional, Sequence

from pydantic import ConfigDict
from sqlalchemy import UniqueConstraint
from sqlmodel import Field, Relationship, SQLModel, Session, create_engine, select


DATABASE_URL = "sqlite:///behavior_manager.db"
_engine = None


class Comment(SQLModel):
    comment_string: str
    created: datetime
    last_modified: datetime
    history: list["Comment"] = Field(default_factory=list)


class StudyMetadata(SQLModel):
    name: str
    file_path: str | None = None
    comments: list[Comment] = Field(default_factory=list)


class VarType(str, Enum):
    _int = "int"
    _bool = "bool"
    _float = "float"

    @property
    def py_type(self) -> type:
        if self is VarType._int:
            return int
        if self is VarType._bool:
            return bool
        return float


class BreedType(str, Enum):
    O = "O"
    T = "T"
    P = "P"
    L = "L"


class Breed(SQLModel):
    name: str
    _type: BreedType


class Variable(SQLModel):
    name: str
    var_type: VarType
    is_observer: bool = False
    is_turtle: bool = False
    is_patch: bool = False
    is_link: bool = False
    breed: str = ""


class VarTable(dict[str, tuple[Variable, Any]]):
    def add(self, name: str, var_type: VarType, value: Any = None) -> None:
        if name in self:
            raise KeyError(f"Variable '{name}' already exists.")
        var = Variable(name=name, var_type=var_type)
        coerced = self._coerce_value(var_type, value)
        super().__setitem__(name, (var, coerced))

    def set(self, name: str, value: Any) -> None:
        var, _ = self._lookup(name)
        coerced = self._coerce_value(var.var_type, value)
        super().__setitem__(name, (var, coerced))

    def get_value(self, name: str) -> Any:
        _, value = self._lookup(name)
        return value

    def get_var(self, name: str) -> Variable:
        var, _ = self._lookup(name)
        return var

    def delete(self, name: str) -> None:
        if name not in self:
            raise KeyError(f"Variable '{name}' does not exist.")
        super().__delitem__(name)

    def __getitem__(self, name: str) -> Any:
        return self.get_value(name)

    def __setitem__(self, name: str, value: Any) -> None:
        if name not in self:
            raise KeyError(f"Variable '{name}' does not exist. Use .add(...) first.")
        self.set(name, value)

    def __delitem__(self, name: str) -> None:
        self.delete(name)

    def _lookup(self, name: str) -> tuple[Variable, Any]:
        if name not in self:
            raise KeyError(f"Variable '{name}' does not exist.")
        var, value = super().__getitem__(name)
        return var, value

    def _coerce_value(self, var_type: VarType, value: Any) -> Any:
        if value is None:
            return None

        t = var_type.py_type

        if t is bool:
            if isinstance(value, bool):
                return value
            if isinstance(value, (int, float)) and value in (0, 1):
                return bool(value)
            if isinstance(value, str):
                v = value.strip().lower()
                if v in {"true", "t", "yes", "y", "1"}:
                    return True
                if v in {"false", "f", "no", "n", "0"}:
                    return False
            raise TypeError(f"Cannot coerce {value!r} to bool.")

        if t is int:
            if isinstance(value, bool):
                raise TypeError("Refusing to treat bool as int.")
            if isinstance(value, int):
                return value
            if isinstance(value, float) and value.is_integer():
                return int(value)
            if isinstance(value, str):
                return int(value.strip())
            raise TypeError(f"Cannot coerce {value!r} to int.")

        if t is float:
            if isinstance(value, bool):
                raise TypeError("Refusing to treat bool as float.")
            if isinstance(value, (int, float)):
                return float(value)
            if isinstance(value, str):
                return float(value.strip())
            raise TypeError(f"Cannot coerce {value!r} to float.")

        raise TypeError(f"Unsupported VarType: {var_type}")


class Adapter(SQLModel, ABC):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    variables: list[Variable] = Field(default_factory=list)
    funcs: list[Callable[[VarTable], bool]] = Field(default_factory=list, exclude=True)

    def required_variable_names(self) -> set[str]:
        return {variable.name for variable in self.variables}

    @abstractmethod
    def modify(self, outcomes: list["Outcome"], variables: VarTable) -> list["Outcome"]:
        raise NotImplementedError

    def odds_effect(self, outcomes: list["Outcome"], variables: VarTable) -> "AdapterEffect":
        return AdapterEffect()


class AdapterEffect(SQLModel):
    logit_delta_by_outcome: dict[str, float] = Field(default_factory=dict)


class AdapterLikelihoodMode(str, Enum):
    multiply = "multiply"
    set = "set"
    add_points = "add_points"
    probability_multiply = "probability_multiply"


class BinaryAdapter(Adapter):
    target_outcome: str
    multiplier: float = 1.0
    likelihood_mode: AdapterLikelihoodMode = AdapterLikelihoodMode.multiply
    set_likelihood: float | None = None
    add_points: float | None = None

    def modify(self, outcomes: list["Outcome"], variables: VarTable) -> list["Outcome"]:
        if any(not func(variables) for func in self.funcs):
            return outcomes

        if self.likelihood_mode == AdapterLikelihoodMode.probability_multiply:
            if self.multiplier < 0.0:
                raise ValueError("BinaryAdapter multiplier must be >= 0 for probability_multiply mode.")
            return _apply_probability_multiply(outcomes, self.target_outcome, self.multiplier)

        updated: list[Outcome] = []
        for outcome in outcomes:
            likelihood = outcome.likelihood
            if outcome.name == self.target_outcome:
                if self.likelihood_mode == AdapterLikelihoodMode.set:
                    if self.set_likelihood is None:
                        raise ValueError("BinaryAdapter set_likelihood is required when likelihood_mode='set'.")
                    likelihood = self.set_likelihood
                elif self.likelihood_mode == AdapterLikelihoodMode.add_points:
                    if self.add_points is None:
                        raise ValueError("BinaryAdapter add_points is required when likelihood_mode='add_points'.")
                    likelihood += self.add_points
                else:
                    likelihood *= self.multiplier
            updated.append(Outcome(name=outcome.name, likelihood=likelihood))
        return updated

    def odds_effect(self, outcomes: list["Outcome"], variables: VarTable) -> AdapterEffect:
        if any(not func(variables) for func in self.funcs):
            return AdapterEffect()
        if self.likelihood_mode in {
            AdapterLikelihoodMode.set,
            AdapterLikelihoodMode.add_points,
            AdapterLikelihoodMode.probability_multiply,
        }:
            raise ValueError(
                f"BinaryAdapter odds mode does not support likelihood_mode='{self.likelihood_mode.value}'."
            )
        if self.multiplier <= 0.0:
            raise ValueError("BinaryAdapter multiplier must be > 0 for odds mode.")
        return AdapterEffect(logit_delta_by_outcome={self.target_outcome: math.log(self.multiplier)})


class LinearAdapter(Adapter):
    target_outcome: str
    intercept: float = 1.0
    coefficients: dict[str, float] = Field(default_factory=dict)
    min_multiplier: float = 0.0
    max_multiplier: float | None = None
    likelihood_mode: AdapterLikelihoodMode = AdapterLikelihoodMode.multiply

    def required_variable_names(self) -> set[str]:
        return super().required_variable_names().union(self.coefficients.keys())

    def _compute_multiplier(self, variables: VarTable) -> float:
        raw_multiplier = self.intercept
        for name, coefficient in self.coefficients.items():
            value = variables.get_value(name)
            if value is None:
                raise ValueError(f"Variable '{name}' is required for LinearAdapter but is None.")
            raw_multiplier += coefficient * float(value)

        multiplier = max(self.min_multiplier, raw_multiplier)
        if self.max_multiplier is not None:
            multiplier = min(self.max_multiplier, multiplier)
        return multiplier

    def modify(self, outcomes: list["Outcome"], variables: VarTable) -> list["Outcome"]:
        if any(not func(variables) for func in self.funcs):
            return outcomes

        multiplier = self._compute_multiplier(variables)
        if self.likelihood_mode == AdapterLikelihoodMode.probability_multiply:
            if multiplier < 0.0:
                raise ValueError("LinearAdapter multiplier must be >= 0 for probability_multiply mode.")
            return _apply_probability_multiply(outcomes, self.target_outcome, multiplier)

        updated: list[Outcome] = []
        for outcome in outcomes:
            likelihood = outcome.likelihood
            if outcome.name == self.target_outcome:
                if self.likelihood_mode == AdapterLikelihoodMode.set:
                    likelihood = multiplier
                elif self.likelihood_mode == AdapterLikelihoodMode.add_points:
                    likelihood += multiplier
                else:
                    likelihood *= multiplier
            updated.append(Outcome(name=outcome.name, likelihood=likelihood))
        return updated

    def odds_effect(self, outcomes: list["Outcome"], variables: VarTable) -> AdapterEffect:
        if any(not func(variables) for func in self.funcs):
            return AdapterEffect()
        if self.likelihood_mode in {
            AdapterLikelihoodMode.set,
            AdapterLikelihoodMode.add_points,
            AdapterLikelihoodMode.probability_multiply,
        }:
            raise ValueError(
                f"LinearAdapter odds mode does not support likelihood_mode='{self.likelihood_mode.value}'."
            )

        multiplier = self._compute_multiplier(variables)
        if multiplier <= 0.0:
            raise ValueError("LinearAdapter multiplier must be > 0 for odds mode.")
        return AdapterEffect(logit_delta_by_outcome={self.target_outcome: math.log(multiplier)})


class Outcome(SQLModel):
    name: str
    likelihood: float


class Context(SQLModel):
    name: str


class Decision(SQLModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    name: str
    description: str
    contexts: list[Context] = Field(default_factory=list)
    outcomes: Optional[list[Outcome]] = None
    adapters: Sequence[Adapter] = Field(default_factory=list)


class Agent(SQLModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    my_variables: VarTable = Field(default_factory=VarTable)
    decisions: list[Decision] = Field(default_factory=list)

    def validate(self, decision: Decision) -> bool:
        if decision.outcomes is None or len(decision.outcomes) == 0:
            return False

        available = set(self.my_variables.keys())
        for adapter in decision.adapters:
            if not adapter.required_variable_names().issubset(available):
                return False
        return True

    def run_decision(self, decision: Decision) -> list[Outcome]:
        outcomes = self.run_decision_raw(decision)
        return _normalize_outcomes(outcomes)

    def run_decision_raw(self, decision: Decision) -> list[Outcome]:
        if not self.validate(decision):
            raise ValueError("Decision is invalid for this agent.")

        assert decision.outcomes is not None
        outcomes = [Outcome(name=o.name, likelihood=o.likelihood) for o in decision.outcomes]
        for adapter in decision.adapters:
            outcomes = adapter.modify(outcomes, self.my_variables)
        return outcomes

    def run_decision_with_odds_mode(self, decision: Decision) -> list[Outcome]:
        if not self.validate(decision):
            raise ValueError("Decision is invalid for this agent.")

        assert decision.outcomes is not None
        base_outcomes = _normalize_outcomes(
            [Outcome(name=o.name, likelihood=o.likelihood) for o in decision.outcomes]
        )
        logits = {outcome.name: math.log(max(outcome.likelihood, 1e-12)) for outcome in base_outcomes}

        for adapter in decision.adapters:
            effect = adapter.odds_effect(base_outcomes, self.my_variables)
            for outcome_name, delta in effect.logit_delta_by_outcome.items():
                if outcome_name not in logits:
                    raise ValueError(f"Adapter effect targets unknown outcome '{outcome_name}'.")
                logits[outcome_name] += delta

        max_logit = max(logits.values())
        exp_scores = {name: math.exp(value - max_logit) for name, value in logits.items()}
        total = sum(exp_scores.values())
        return [
            Outcome(name=outcome.name, likelihood=exp_scores[outcome.name] / total)
            for outcome in base_outcomes
        ]

    def get_required_variables(self) -> set[str]:
        return set(self.my_variables.keys())


# --- ORM models (SQLite via SQLModel) ---


class Study(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    name: str
    file_path: str | None = None

    comments: list["StudyComment"] = Relationship(back_populates="study")
    adapter_sets: list["AdapterSetRecord"] = Relationship(back_populates="study")


class StudyComment(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    study_id: int = Field(foreign_key="study.id", index=True)
    parent_id: int | None = Field(default=None, foreign_key="studycomment.id", index=True)

    comment_string: str
    created: datetime = Field(default_factory=datetime.utcnow)
    last_modified: datetime = Field(default_factory=datetime.utcnow)

    study: Study | None = Relationship(back_populates="comments")
    parent: Optional["StudyComment"] = Relationship(
        back_populates="history",
        sa_relationship_kwargs={"remote_side": "StudyComment.id"},
    )
    history: list["StudyComment"] = Relationship(back_populates="parent")


class AgentRecord(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    name: str = "agent"

    variables: list["VariableRecord"] = Relationship(back_populates="agent")
    decisions: list["DecisionRecord"] = Relationship(back_populates="agent")


class VariableRecord(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    agent_id: int = Field(foreign_key="agentrecord.id", index=True)

    name: str
    var_type: VarType
    is_observer: bool = False
    is_turtle: bool = False
    is_patch: bool = False
    is_link: bool = False
    breed: str = ""

    value_int: int | None = None
    value_float: float | None = None
    value_bool: bool | None = None

    agent: AgentRecord | None = Relationship(back_populates="variables")
    coefficients: list["LinearCoefficientRecord"] = Relationship(back_populates="variable")
    predicates: list["PredicateRecord"] = Relationship(back_populates="variable")


class DecisionContextLinkRecord(SQLModel, table=True):
    decision_id: int = Field(foreign_key="decisionrecord.id", primary_key=True)
    context_id: int = Field(foreign_key="contextrecord.id", primary_key=True)


class ContextRecord(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    name: str

    decisions: list["DecisionRecord"] = Relationship(
        back_populates="contexts",
        link_model=DecisionContextLinkRecord,
    )


class DecisionRecord(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    agent_id: int | None = Field(default=None, foreign_key="agentrecord.id", index=True)

    name: str
    description: str

    agent: AgentRecord | None = Relationship(back_populates="decisions")
    contexts: list[ContextRecord] = Relationship(
        back_populates="decisions",
        link_model=DecisionContextLinkRecord,
    )
    outcomes: list["OutcomeRecord"] = Relationship(back_populates="decision")
    adapter_sets: list["AdapterSetRecord"] = Relationship(back_populates="decision")


class OutcomeRecord(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    decision_id: int = Field(foreign_key="decisionrecord.id", index=True)

    name: str
    likelihood: float | None = None

    decision: DecisionRecord | None = Relationship(back_populates="outcomes")
    targeted_by_effects: list["AdapterRecord"] = Relationship(back_populates="target_outcome")


class AdapterType(str, Enum):
    binary = "binary"
    linear = "linear"


class ConditionOperator(str, Enum):
    eq = "eq"
    ne = "ne"
    gt = "gt"
    gte = "gte"
    lt = "lt"
    lte = "lte"


class DatasetFieldType(str, Enum):
    _int = "int"
    _float = "float"
    _bool = "bool"
    _string = "string"


class AdapterRecord(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    adapter_set_id: int = Field(foreign_key="adaptersetrecord.id", index=True)
    target_outcome_id: int = Field(foreign_key="outcomerecord.id", index=True)
    order_index: int = 0

    adapter_type: AdapterType
    likelihood_mode: AdapterLikelihoodMode = AdapterLikelihoodMode.multiply

    multiplier: float | None = None
    set_likelihood: float | None = None
    add_points: float | None = None
    intercept: float | None = None
    min_multiplier: float | None = None
    max_multiplier: float | None = None

    adapter_set: Optional["AdapterSetRecord"] = Relationship(back_populates="effects")
    target_outcome: OutcomeRecord | None = Relationship(back_populates="targeted_by_effects")
    coefficients: list["LinearCoefficientRecord"] = Relationship(back_populates="effect")


class AdapterSetRecord(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    decision_id: int = Field(foreign_key="decisionrecord.id", index=True)
    study_id: int | None = Field(default=None, foreign_key="study.id", index=True)
    name: str = "Rule Set"
    order_index: int = 0

    decision: DecisionRecord | None = Relationship(back_populates="adapter_sets")
    study: Study | None = Relationship(back_populates="adapter_sets")
    effects: list[AdapterRecord] = Relationship(back_populates="adapter_set")
    predicate_groups: list["ConditionChainRecord"] = Relationship(back_populates="adapter_set")


class LinearCoefficientRecord(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    adapter_id: int = Field(foreign_key="adapterrecord.id", index=True)
    variable_id: int = Field(foreign_key="variablerecord.id", index=True)
    coefficient: float

    effect: AdapterRecord | None = Relationship(back_populates="coefficients")
    variable: VariableRecord | None = Relationship(back_populates="coefficients")


class ConditionCombinator(str, Enum):
    all = "all"
    any = "any"


class ConditionChainRecord(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    adapter_set_id: int = Field(foreign_key="adaptersetrecord.id", index=True)
    name: str = "Chain"
    combinator: ConditionCombinator = ConditionCombinator.all
    order_index: int = 0

    adapter_set: AdapterSetRecord | None = Relationship(back_populates="predicate_groups")
    predicates: list["PredicateRecord"] = Relationship(back_populates="chain")


class PredicateRecord(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    chain_id: int = Field(foreign_key="conditionchainrecord.id", index=True)
    variable_id: int = Field(foreign_key="variablerecord.id", index=True)
    operator: ConditionOperator
    order_index: int = 0

    value_int: int | None = None
    value_float: float | None = None
    value_bool: bool | None = None

    chain: ConditionChainRecord | None = Relationship(back_populates="predicates")
    variable: VariableRecord | None = Relationship(back_populates="predicates")


class DatasetRecord(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    name: str = Field(index=True, sa_column_kwargs={"unique": True})

    fields: list["DatasetFieldRecord"] = Relationship(back_populates="dataset")
    datapoints: list["DatapointRecord"] = Relationship(back_populates="dataset")


class DatasetFieldRecord(SQLModel, table=True):
    __table_args__ = (
        UniqueConstraint("dataset_id", "name", name="uq_dataset_field_name"),
        UniqueConstraint("dataset_id", "order_index", name="uq_dataset_field_order"),
    )

    id: int | None = Field(default=None, primary_key=True)
    dataset_id: int = Field(foreign_key="datasetrecord.id", index=True)

    name: str
    field_type: DatasetFieldType
    order_index: int = 0

    default_int: int | None = None
    default_float: float | None = None
    default_bool: bool | None = None
    default_string: str | None = None

    dataset: DatasetRecord | None = Relationship(back_populates="fields")
    datapoint_values: list["DatapointValueRecord"] = Relationship(back_populates="field")


class DatapointRecord(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    dataset_id: int = Field(foreign_key="datasetrecord.id", index=True)

    dataset: DatasetRecord | None = Relationship(back_populates="datapoints")
    values: list["DatapointValueRecord"] = Relationship(back_populates="datapoint")


class DatapointValueRecord(SQLModel, table=True):
    __table_args__ = (UniqueConstraint("datapoint_id", "field_id", name="uq_datapoint_field_value"),)

    id: int | None = Field(default=None, primary_key=True)
    datapoint_id: int = Field(foreign_key="datapointrecord.id", index=True)
    field_id: int = Field(foreign_key="datasetfieldrecord.id", index=True)

    value_int: int | None = None
    value_float: float | None = None
    value_bool: bool | None = None
    value_string: str | None = None

    datapoint: DatapointRecord | None = Relationship(back_populates="values")
    field: DatasetFieldRecord | None = Relationship(back_populates="datapoint_values")


# Domain aliases using requested terminology.
RuleRecord = AdapterRecord
PredicateGroupRecord = ConditionChainRecord
RuleChainRecord = DecisionRecord


# --- DB helpers ---


def get_engine(db_url: str = DATABASE_URL):
    global _engine
    if _engine is None:
        _engine = create_engine(db_url, echo=False, connect_args={"check_same_thread": False})
    return _engine


def init_db(db_url: str = DATABASE_URL) -> None:
    engine = get_engine(db_url)
    SQLModel.metadata.create_all(engine)
    _ensure_adapter_set_study_column(engine)


def _ensure_adapter_set_study_column(engine) -> None:
    with engine.begin() as connection:
        columns = {
            row[1]
            for row in connection.exec_driver_sql('PRAGMA table_info("adaptersetrecord")').fetchall()
        }
        if 'study_id' not in columns:
            connection.exec_driver_sql('ALTER TABLE "adaptersetrecord" ADD COLUMN "study_id" INTEGER')


def get_session(db_url: str = DATABASE_URL) -> Iterator[Session]:
    with Session(get_engine(db_url)) as session:
        yield session


def create_study(session: Session, name: str, file_path: str | None = None) -> Study:
    study = Study(name=name, file_path=file_path)
    session.add(study)
    session.commit()
    session.refresh(study)
    return study


def list_studies(session: Session) -> list[Study]:
    return list(session.exec(select(Study).order_by(Study.name)))


def add_study_comment(
    session: Session,
    study_id: int,
    comment_string: str,
    parent_id: int | None = None,
) -> StudyComment:
    now = datetime.utcnow()
    comment = StudyComment(
        study_id=study_id,
        parent_id=parent_id,
        comment_string=comment_string,
        created=now,
        last_modified=now,
    )
    session.add(comment)
    session.commit()
    session.refresh(comment)
    return comment


def create_agent_record(session: Session, name: str = "agent") -> AgentRecord:
    record = AgentRecord(name=name)
    session.add(record)
    session.commit()
    session.refresh(record)
    return record


def _coerce_value_for_storage(var_type: VarType, value: Any) -> tuple[int | None, float | None, bool | None]:
    if value is None:
        return None, None, None

    if var_type is VarType._bool:
        if isinstance(value, bool):
            return None, None, value
        if isinstance(value, (int, float)) and value in (0, 1):
            return None, None, bool(value)
        if isinstance(value, str):
            v = value.strip().lower()
            if v in {"true", "t", "yes", "y", "1"}:
                return None, None, True
            if v in {"false", "f", "no", "n", "0"}:
                return None, None, False
        raise TypeError(f"Cannot coerce {value!r} to bool.")

    if var_type is VarType._int:
        if isinstance(value, bool):
            raise TypeError("Refusing to treat bool as int.")
        if isinstance(value, int):
            return value, None, None
        if isinstance(value, float) and value.is_integer():
            return int(value), None, None
        if isinstance(value, str):
            return int(value.strip()), None, None
        raise TypeError(f"Cannot coerce {value!r} to int.")

    if isinstance(value, bool):
        raise TypeError("Refusing to treat bool as float.")
    if isinstance(value, (int, float)):
        return None, float(value), None
    if isinstance(value, str):
        return None, float(value.strip()), None
    raise TypeError(f"Cannot coerce {value!r} to float.")


def add_agent_variable(
    session: Session,
    agent_id: int,
    name: str,
    var_type: VarType,
    value: Any = None,
    *,
    is_observer: bool = False,
    is_turtle: bool = False,
    is_patch: bool = False,
    is_link: bool = False,
    breed: str = "",
) -> VariableRecord:
    value_int, value_float, value_bool = _coerce_value_for_storage(var_type, value)
    record = VariableRecord(
        agent_id=agent_id,
        name=name,
        var_type=var_type,
        is_observer=is_observer,
        is_turtle=is_turtle,
        is_patch=is_patch,
        is_link=is_link,
        breed=breed,
        value_int=value_int,
        value_float=value_float,
        value_bool=value_bool,
    )
    session.add(record)
    session.commit()
    session.refresh(record)
    return record


def create_decision_record(
    session: Session,
    name: str,
    description: str,
    agent_id: int | None = None,
    context_ids: list[int] | None = None,
) -> DecisionRecord:
    record = DecisionRecord(agent_id=agent_id, name=name, description=description)
    if context_ids:
        contexts = list(
            session.exec(select(ContextRecord).where(ContextRecord.id.in_(context_ids)))
        )
        record.contexts = contexts
    session.add(record)
    session.commit()
    session.refresh(record)
    return record


def add_outcome_record(
    session: Session,
    decision_id: int,
    name: str,
    likelihood: float | None = None,
) -> OutcomeRecord:
    outcome = OutcomeRecord(decision_id=decision_id, name=name, likelihood=likelihood)
    session.add(outcome)
    session.commit()
    session.refresh(outcome)
    return outcome


def _normalize_outcomes(outcomes: list[Outcome]) -> list[Outcome]:
    if not outcomes:
        return outcomes

    total = sum(max(0.0, outcome.likelihood) for outcome in outcomes)
    if total == 0.0:
        uniform = 1.0 / len(outcomes)
        return [Outcome(name=outcome.name, likelihood=uniform) for outcome in outcomes]

    normalized: list[Outcome] = []
    for outcome in outcomes:
        clipped = max(0.0, outcome.likelihood)
        normalized.append(Outcome(name=outcome.name, likelihood=clipped / total))
    return normalized


def _coerce_dataset_value(field_type: DatasetFieldType, raw_value: Any) -> tuple[int | None, float | None, bool | None, str | None]:
    if raw_value is None:
        raise TypeError("Dataset values cannot be null.")

    if field_type == DatasetFieldType._int:
        if isinstance(raw_value, bool):
            raise TypeError("Boolean cannot be used as int.")
        if isinstance(raw_value, int):
            return raw_value, None, None, None
        if isinstance(raw_value, float) and raw_value.is_integer():
            return int(raw_value), None, None, None
        if isinstance(raw_value, str):
            text = raw_value.strip()
            if text == "":
                raise TypeError("Dataset int value cannot be empty.")
            return int(text), None, None, None
        raise TypeError(f"Cannot coerce {raw_value!r} to int.")

    if field_type == DatasetFieldType._float:
        if isinstance(raw_value, bool):
            raise TypeError("Boolean cannot be used as float.")
        if isinstance(raw_value, (int, float)):
            return None, float(raw_value), None, None
        if isinstance(raw_value, str):
            text = raw_value.strip()
            if text == "":
                raise TypeError("Dataset float value cannot be empty.")
            return None, float(text), None, None
        raise TypeError(f"Cannot coerce {raw_value!r} to float.")

    if field_type == DatasetFieldType._bool:
        if isinstance(raw_value, bool):
            return None, None, raw_value, None
        if isinstance(raw_value, (int, float)) and raw_value in (0, 1):
            return None, None, bool(raw_value), None
        if isinstance(raw_value, str):
            text = raw_value.strip().lower()
            if text in {"true", "t", "yes", "y", "1"}:
                return None, None, True, None
            if text in {"false", "f", "no", "n", "0"}:
                return None, None, False, None
        raise TypeError(f"Cannot coerce {raw_value!r} to bool.")

    if isinstance(raw_value, str):
        return None, None, None, raw_value
    return None, None, None, str(raw_value)


def _apply_probability_multiply(outcomes: list[Outcome], target_outcome: str, factor: float) -> list[Outcome]:
    probs = _normalize_outcomes(outcomes)
    target_prob = next((outcome.likelihood for outcome in probs if outcome.name == target_outcome), None)
    if target_prob is None:
        return outcomes

    new_target_prob = min(1.0, max(0.0, target_prob * factor))
    remaining_old = max(0.0, 1.0 - target_prob)
    remaining_new = max(0.0, 1.0 - new_target_prob)

    if remaining_old == 0.0:
        return [
            Outcome(name=outcome.name, likelihood=(1.0 if outcome.name == target_outcome else 0.0))
            for outcome in probs
        ]

    updated: list[Outcome] = []
    for outcome in probs:
        if outcome.name == target_outcome:
            updated.append(Outcome(name=outcome.name, likelihood=new_target_prob))
            continue
        share = outcome.likelihood / remaining_old
        updated.append(Outcome(name=outcome.name, likelihood=share * remaining_new))
    return updated
