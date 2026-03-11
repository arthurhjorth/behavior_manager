# Core Mechanics

`example.py` is the simplest entry point for understanding the core mechanics of the project. It does not show the full study-linking workflow from the GUI. Instead, it shows the in-memory decision model that the rest of the system builds on.

## Main Building Blocks

- `Variable`: a named input used by a decision, such as `age`
- `Outcome`: a possible result, such as `heads` or `tails`
- `Decision`: a collection of outcomes plus a set of adapters
- `BinaryAdapter`: a conditional rule that changes one outcome when its predicates are true
- `LinearAdapter`: a rule that changes one outcome as a linear function of one or more variables
- `Agent`: a holder of variable values that can run a decision

## Evaluation Flow

The flow in `example.py` is:

1. Define one or more baseline outcomes.
2. Define a decision with those outcomes.
3. Optionally attach adapters that modify outcome likelihoods.
4. Create an agent and assign variable values.
5. Run the decision and inspect the adjusted outcome distribution.

`example.py` walks through three small cases:

1. A fair coin toss with no adapters.
2. A binary adapter where `heads` is favored when `age > 35`.
3. A linear adapter where the likelihood of `heads` changes continuously with age.

It also compares two execution paths, `run_decision(...)` and `run_decision_with_odds_mode(...)`, so you can see how the same building blocks behave under the two calculation modes currently implemented in the project.

## Reading `example.py`

The examples in `example.py` are intentionally small and build on each other.

### 1. Baseline Decision

The first example creates a decision with two outcomes and no adapters:

```python
fair_coin = Decision(
    name="fair_coin_toss",
    description="A fair coin toss with no adapters.",
    outcomes=[heads, tails],
    adapters=[],
)
```

This is the baseline case. The decision starts with a 50/50 distribution and nothing modifies it.

### 2. Binary Adapter

The second example adds a conditional rule:

```python
binary_adapter = BinaryAdapter(
    variables=[age],
    funcs=[lambda vars_table: vars_table.get_value("age") > 35],
    target_outcome="heads",
    multiplier=2.0,
)
```

This says: if the agent's `age` is greater than 35, multiply the likelihood of `heads` by 2. The same decision is then run for different agents with different values of `age`, which shows how variable values activate or deactivate an adapter.

### 3. Linear Adapter

The third example uses a continuous adjustment instead of a threshold:

```python
linear_adapter = LinearAdapter(
    variables=[age],
    target_outcome="heads",
    intercept=0.6,
    coefficients={"age": 0.02},
    min_multiplier=0.1,
    max_multiplier=3.0,
)
```

This computes a multiplier from the variable values. In this case, the multiplier grows with age, but is clipped to stay within the configured minimum and maximum.

### 4. Comparing Execution Modes

The helper function `run_both_paths(...)` runs the same decision through:

- `run_decision(...)`
- `run_decision_with_odds_mode(...)`

That makes `example.py` useful not just as a usage example, but also as a quick check for how the two calculation paths differ on the same inputs.
