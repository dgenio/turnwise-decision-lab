"""Same task, same tools, different controller (#49).

A minimal architectural demonstration, not a benchmark and not an agent framework:

* ``world``: one synthetic incident snapshot, one tool catalog and one host, shared
  by every configuration.
* ``model``: one deterministic stand-in for "the same capable model".
* ``native_openai``: a conventional OpenAI Agents SDK ``Agent`` + ``Runner``. The model
  decides every next tool call and the Runner executes it (optional dependency).
* ``turnwise``: the same model and tools under a per-step policy. A model's tool
  request is an observation; the policy regains control and decides what runs.

Run ``python -m turnwise_lab.control_demo`` for both per-step traces.
"""
