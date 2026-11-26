# P6: continuous learning research protocol
Uses existing immutable outcome lessons, not a new AI model. From the staged checkout, run:
```sh
python3 -m recover_trading.learning_intelligence --journal /path/to/learning.sqlite --symbol XAUTUSD --mode feedback
python3 -m recover_trading.learning_intelligence --journal /path/to/learning.sqlite --symbol XAUTUSD --mode freeze --rule G01 --direction LONG --expected lower > research-plan.json
python3 -m recover_trading.learning_intelligence --journal /path/to/learning.sqlite --symbol XAUTUSD --mode evaluate --plan research-plan.json
```
The example hypothesis is illustrative only, not a strategy recommendation. Freeze a single hypothesis before observing future outcomes; independently timestamp/version the plan. Evaluation rechecks the development digest and only accepts later-opened, later-enrolled, reconciled episodes. Twenty samples per group per period is a preliminary research coverage requirement, not a trading gate or statistical proof. Descriptive replication does not validate a causal improvement and does not promote a lesson. Actual independent forward comparison and human approval remain required. No live feedback, prompts, model settings, service or orders changed. No Kimi/Opus or paid calls.
