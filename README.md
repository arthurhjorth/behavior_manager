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

This project tries to provide [meaningful building blocks](docs/core_mechanics.md) for that. It also contains a [nicegui-based GUI server](docs/server_workflow.md) for working with these building blocks and a DB-backed [population module](docs/population_module.md) for importing population workbooks and running matching workflows.


# Installing and running
```
git@github.com:arthurhjorth/behavior_manager.git
cd behavior_manager
python -m venv .venv ## this will depend on whether you have an alias for python. otherwise use python3.12, or whatever.
. .venv/bin/activate
pip install -r requirements.txt
python server.py
```

This will start the server on port `8080`.


# Creating database with population studies

You can add individual XLS files but if we want to add all our population datasets in one go and avoid having to configure them individually, then first copy the `popuation_data` folder from the shared BSS SharePoint/Task 1. Then run

`.venv/bin/python services/population_migration_service.py`

It's about 400MB of data, so it takes a while. but this will put all the population studies, questionnaire-items, and respones per individual in the local sqlite databse
