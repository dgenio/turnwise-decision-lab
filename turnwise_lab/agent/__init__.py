"""v0.6: a bounded, decision-driven execution loop.

A lightweight decision model repeatedly proposes the next operation for ONE
user turn (call a tool, run a workflow, call a light or heavy generation
model, finish with verified data, clarify, abstain). An independent host
validates every proposal before anything runs, every observation is fed back
into the next decision, and a context step assembles only the prompt blocks a
generation call needs.

Not a framework: one loop, one host policy, a handful of typed contracts.
"""
