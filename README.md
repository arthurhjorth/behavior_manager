# BehaviorManager

The purpose of this project is to keep track of how evidence informs agent-based models.

The fundamental assumption in this project is that we can describe two different kinds of operations:
1. Agents behave (often subconsciously), and
2. Agents change (their minds, attitudes, etc.)
and for both, we can describe a set of outcomes and their probability distributions given a specific set of conditions.

For scientific modelling, we want these probability distributions to be evidence-based. Consequently, we want a consistent way of connecting 
* a piece of evidence from a specific study to
* an agent behavior or agent change, and
* the specific implementation and its effect on outcome probabilities

This project tries to provide [meaningful building blocks](docs/core_mechanics.md) for that. It also contains a [GUI server](docs/server_workflow.md) for working with these building blocks.
