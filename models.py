from abc import ABC, abstractmethod
from datetime import datetime
from enum import Enum
import math
from typing import Any, Callable, Iterator, Optional, Sequence

from pydantic import ConfigDict
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


class BinaryAdapter(Adapter):
    target_outcome: str
    multiplier: float = 1.0

    def modify(self, outcomes: list["Outcome"], variables: VarTable) -> list["Outcome"]:
        if any(not func(variables) for func in self.funcs):
            return outcomes

        updated: list[Outcome] = []
        for outcome in outcomes:
            likelihood = outcome.likelihood
            if outcome.name == self.target_outcome:
                likelihood *= self.multiplier
            updated.append(Outcome(name=outcome.name, likelihood=likelihood))
        return _normalize_outcomes(updated)

    def odds_effect(self, outcomes: list["Outcome"], variables: VarTable) -> AdapterEffect:
        if any(not func(variables) for func in self.funcs):
            return AdapterEffect()
        if self.multiplier <= 0.0:
            raise ValueError("BinaryAdapter multiplier must be > 0 for odds mode.")
        return AdapterEffect(logit_delta_by_outcome={self.target_outcome: math.log(self.multiplier)})


class LinearAdapter(Adapter):
    target_outcome: str
    intercept: float = 1.0
    coefficients: dict[str, float] = Field(default_factory=dict)
    min_multiplier: float = 0.0
    max_multiplier: float | None = None

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

        updated: list[Outcome] = []
        for outcome in outcomes:
            likelihood = outcome.likelihood
            if outcome.name == self.target_outcome:
                likelihood *= multiplier
            updated.append(Outcome(name=outcome.name, likelihood=likelihood))
        return _normalize_outcomes(updated)

    def odds_effect(self, outcomes: list["Outcome"], variables: VarTable) -> AdapterEffect:
        if any(not func(variables) for func in self.funcs):
            return AdapterEffect()

        multiplier = self._compute_multiplier(variables)
        if multiplier <= 0.0:
            raise ValueError("LinearAdapter multiplier must be > 0 for odds mode.")
        return AdapterEffect(logit_delta_by_outcome={self.target_outcome: math.log(multiplier)})


class Outcome(SQLModel):
    name: str
    likelihood: float


class Decision(SQLModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    name: str
    description: str
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
        if not self.validate(decision):
            raise ValueError("Decision is invalid for this agent.")

        assert decision.outcomes is not None
        outcomes = [Outcome(name=o.name, likelihood=o.likelihood) for o in decision.outcomes]
        for adapter in decision.adapters:
            outcomes = adapter.modify(outcomes, self.my_variables)
        return _normalize_outcomes(outcomes)

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


class DecisionRecord(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    agent_id: int = Field(foreign_key="agentrecord.id", index=True)

    name: str
    description: str

    agent: AgentRecord | None = Relationship(back_populates="decisions")
    outcomes: list["OutcomeRecord"] = Relationship(back_populates="decision")
    adapters: list["AdapterRecord"] = Relationship(back_populates="decision")


class OutcomeRecord(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    decision_id: int = Field(foreign_key="decisionrecord.id", index=True)

    name: str
    likelihood: float | None = None

    decision: DecisionRecord | None = Relationship(back_populates="outcomes")
    targeted_by_adapters: list["AdapterRecord"] = Relationship(back_populates="target_outcome")


class AdapterType(str, Enum):
    binary = "binary"
    linear = "linear"


class AdapterRecord(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    decision_id: int = Field(foreign_key="decisionrecord.id", index=True)
    target_outcome_id: int = Field(foreign_key="outcomerecord.id", index=True)

    adapter_type: AdapterType

    multiplier: float | None = None
    intercept: float | None = None
    min_multiplier: float | None = None
    max_multiplier: float | None = None

    decision: DecisionRecord | None = Relationship(back_populates="adapters")
    target_outcome: OutcomeRecord | None = Relationship(back_populates="targeted_by_adapters")
    coefficients: list["LinearCoefficientRecord"] = Relationship(back_populates="adapter")


class LinearCoefficientRecord(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    adapter_id: int = Field(foreign_key="adapterrecord.id", index=True)
    variable_id: int = Field(foreign_key="variablerecord.id", index=True)
    coefficient: float

    adapter: AdapterRecord | None = Relationship(back_populates="coefficients")
    variable: VariableRecord | None = Relationship(back_populates="coefficients")


# --- DB helpers ---


def get_engine(db_url: str = DATABASE_URL):
    global _engine
    if _engine is None:
        _engine = create_engine(db_url, echo=False, connect_args={"check_same_thread": False})
    return _engine


def init_db(db_url: str = DATABASE_URL) -> None:
    engine = get_engine(db_url)
    SQLModel.metadata.create_all(engine)


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


def create_decision_record(session: Session, agent_id: int, name: str, description: str) -> DecisionRecord:
    record = DecisionRecord(agent_id=agent_id, name=name, description=description)
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
