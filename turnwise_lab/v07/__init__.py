"""v0.7 exit-gate study: evidence contracts checked by the host at the exit of a turn.

Nothing in this package changes the frozen v0.6 experiment. It reuses the v0.6
host, loop, controllers and models unchanged and adds:

* ``world``       five extra world variants (temporal reversal, two deploys, ...);
* ``evidence``    evidence roles, claim typing, contracts and host-derived facts;
* ``gate``        the exit gate (pre-terminal sufficiency, action latch, grounding);
* ``controllers`` gate wrappers for every v0.6 controller and the contract planner;
* ``bench``       the paired benchmark, scorer, full cost ledger and report;
* ``hosted``      an opt-in capable-agent adapter (never run without approval).
"""
