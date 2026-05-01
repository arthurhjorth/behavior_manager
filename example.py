from models import Agent, BinaryAdapter, Decision, LinearAdapter, Outcome, VarType, Variable


def print_outcomes(label: str, outcomes: list[Outcome]) -> None:
    print(label)
    for outcome in outcomes:
        print(f"  - {outcome.name}: {outcome.likelihood:.3f}")


def run_both_paths(agent: Agent, decision: Decision, age: int) -> None:
    print(f"\nAge = {age}")
    old_path = agent.run_decision(decision)
    new_path = agent.run_decision_with_odds_mode(decision)
    print_outcomes("Old path (run_decision):", old_path)
    print_outcomes("New path (run_decision_with_odds_mode):", new_path)


def base_coin_outcomes() -> list[Outcome]:
    return [
        Outcome(name="heads", likelihood=0.5),
        Outcome(name="tails", likelihood=0.5),
    ]


def main() -> None:
    age = Variable(name="age", var_type=VarType._int) 
    heads = Outcome(name="heads", likelihood=0.5)
    tails = Outcome(name="tails", likelihood=0.5)
    fair_coin = Decision(
        name="fair_coin_toss",
        description="A fair coin toss with no adapters.",
        outcomes=[heads, tails],
        adapters=[],
    )
    fair_agent = Agent() # an agent with no variables. It's basically just a class for running decisions.
    fair_results = fair_agent.run_decision(fair_coin)
    print("Fair coin toss")
    print_outcomes("Result:", fair_results)

    binary_adapter = BinaryAdapter(
        variables=[age],
        funcs=[lambda vars_table: vars_table.get_value("age") > 35],
        target_outcome="heads",
        multiplier=2.0,
    )
    binary_decision = Decision(
        name="binary_age_adjusted_coin_toss",
        description="Heads is doubled if age > 35.",
        outcomes=base_coin_outcomes(),
        adapters=[binary_adapter],
    )

    print("\nBinary adapter comparison")
    for agent_age in [10, 40]:
        agent = Agent()
        agent.my_variables.add(name="age", var_type=VarType._int, value=agent_age)
        run_both_paths(agent, binary_decision, agent_age)

    linear_adapter = LinearAdapter(
        variables=[age],
        target_outcome="heads",
        intercept=0.6,
        coefficients={"age": 0.02},
        min_multiplier=0.1,
        max_multiplier=3.0,
    )
    linear_decision = Decision(
        name="linear_age_adjusted_coin_toss",
        description="Heads changes linearly with age.",
        outcomes=base_coin_outcomes(),
        adapters=[linear_adapter],
    )

    print("\nLinear adapter comparison")
    for age in [10, 40, 70]:
        agent = Agent()
        agent.my_variables.add(name="age", var_type=VarType._int, value=age)
        run_both_paths(agent, linear_decision, age)


if __name__ == "__main__":
    main()
