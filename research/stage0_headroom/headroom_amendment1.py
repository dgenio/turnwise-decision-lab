"""Stage 0, amendment 1: τ²-bench, a coding set and the tier ceiling (PROTOCOL-AMENDMENT-1.md, issue #86).

Reuses ``headroom.py`` (PROTOCOL.md) unchanged for the token estimator, the cost model, the price cards, the
leaf test, the bootstrap and the aggregation, and adds only what the amendment defines: the τ²-bench and
TwinRouterBench readers, multi-call turns, the bash-to-tool mapping, D0 rules for the new domains, the tier
ceiling, the calibration and the combined decision rule. Standard library only. Data files are parsed as JSON
and source files with ``ast``; nothing from the data clones is imported or executed.

    python -I research/stage0_headroom/headroom_amendment1.py --tau2-root /path/to/tau2-bench \\
        --tau2-tools-root /path/to/tau2-bench@v0.1.0 --twinrouter-root /path/to/TwinRouterBench --split train
    ... --split eval --json-out research/stage0_headroom/results-amendment-1.json
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import importlib.util
import json
import shlex
import statistics
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

_HERE = Path(__file__).resolve().parent
_SPEC = importlib.util.spec_from_file_location("stage0_headroom", _HERE / "headroom.py")
h = sys.modules.get("stage0_headroom") or importlib.util.module_from_spec(_SPEC)
if "stage0_headroom" not in sys.modules:
    sys.modules["stage0_headroom"] = h  # dataclasses resolves annotations through sys.modules
    _SPEC.loader.exec_module(h)

# ---------------------------------------------------------------- pins (PROTOCOL-AMENDMENT-1.md)
TAU2_COMMIT = "768f3d8fe8528b4f32a5096f9ed008ae50f48ead"
TAU2_DIR = "data/tau2/results/final"
TAU2_FILES = {  # file -> (domain key, agent model, sha256)
    "claude-3-7-sonnet-20250219_airline_default_gpt-4.1-2025-04-14_4trials.json":
        ("tau2-airline", "claude-3-7-sonnet", "40a2c6a246eab27db5cdefda895fbe7f44be78a23d300817248534aa606d66de"),
    "claude-3-7-sonnet-20250219_retail_default_gpt-4.1-2025-04-14_4trials.json":
        ("tau2-retail", "claude-3-7-sonnet", "ed41dbd18c080154156484e3a0122c095e324a11367a640d88e15956daed7b9d"),
    "claude-3-7-sonnet-20250219_telecom_default_gpt-4.1-2025-04-14_4trials.json":
        ("tau2-telecom", "claude-3-7-sonnet", "f49e540896fe91ab8631647f02eb777ef6fed5a6ebec545f43e71d0504e227b2"),
    "gpt-4.1-2025-04-14_airline_default_gpt-4.1-2025-04-14_4trials.json":
        ("tau2-airline", "gpt-4.1", "31d19e79b8ddc5934a60701f913ff5fefb41dee5e68f7b813c26254ab2e2d5c8"),
    "gpt-4.1-2025-04-14_retail_default_gpt-4.1-2025-04-14_4trials.json":
        ("tau2-retail", "gpt-4.1", "5fc5b96ada0fe46a463eaed98d1bfed9947fe073bac052290162dae18d71394e"),
    "gpt-4.1-2025-04-14_telecom_default_gpt-4.1-2025-04-14_4trials.json":
        ("tau2-telecom", "gpt-4.1", "8e1793f57a9e216514dbce1f93b44b0592d5904f1c5b97ab711906782107a1f2"),
    "o4-mini-2025-04-16_airline_default_gpt-4.1-2025-04-14_4trials.json":
        ("tau2-airline", "o4-mini", "6a3a354c9bce42b52905af096e9cea6f555548acbb17b567fd403c356df7b4ec"),
    "o4-mini-2025-04-16_retail_default_gpt-4.1-2025-04-14_4trials.json":
        ("tau2-retail", "o4-mini", "7135f38bbbbd46d6babe830574c8623bb276d8fd6da316580b905cf513853f98"),
    "o4-mini-2025-04-16_telecom_default_gpt-4.1-2025-04-14_4trials.json":
        ("tau2-telecom", "o4-mini", "1f46a6f296694bdb3ae203e6b379cdada0b8f17b648a4cf90d6343de1f1fb070"),
}
TAU2_TOOLS_TAG = "v0.1.0"
TAU2_TOOLS = {  # domain key -> (path under the v0.1.0 checkout, sha256)
    "tau2-airline": ("src/tau2/domains/airline/tools.py",
                     "3987f21c286314cb48764f97052934ff4fd60e27a0b2e4a43423911adf8eaa26"),
    "tau2-retail": ("src/tau2/domains/retail/tools.py",
                    "7063727dfcaa428d2b78745ed025210312f080506c3d24a7059383945e50613f"),
    "tau2-telecom": ("src/tau2/domains/telecom/tools.py",
                     "388552434d1b8225e33e7958bdb6efccfe92b49e11d1838568d9b559514e9d01"),
}
TWIN_COMMIT = "1f9c3aac01d82d27d81ef1f2ff3d04f279348ecb"
TWIN_FILES = {
    "data/static/question_bank.jsonl": "5b4f90c24643b214a9b0f26bf4e05afc742554262f4ef405e0b3b4a4cce503f4",
    "data/dynamic/tier_to_model.json": "10c14b0c2d2a8fd096280504c7aae9acf948abf74f590bd6ea8ac6689d138c4f",
    "data/dynamic/model_pricing.json": "1638ca92ea47ee4c70db09e078c58a71fa85bde623d76123d421b1c11749832a",
}
TAU2_DOMAINS = ("tau2-airline", "tau2-retail", "tau2-telecom")
CODING = "swebench"
TAU_BENCH_DOMAINS = ("airline", "retail")  # from the committed results.json (#97)

READ_PROGRAMS = frozenset("cat head tail ls find grep egrep rg nl wc pwd file stat tree sort uniq cut diff".split())
READ_GIT = frozenset({"git diff", "git log", "git show", "git status"})
SEGMENT_OPS = frozenset({"&&", "||", ";", "|", "&"})
REDIRECTS = frozenset({">", ">>", ">|", "&>", "&>>"})


def _verify(path: Path, expected: str) -> bytes:
    data = path.read_bytes()
    actual = hashlib.sha256(data).hexdigest()
    if actual != expected:
        raise SystemExit(f"{path}: SHA-256 {actual} does not match the amendment ({expected}); refusing to run")
    return data


# ---------------------------------------------------------------- calls and turns
@dataclass
class Call:
    name: str
    raw: str  # text billed as the call (JSON arguments, or the bash command's JSON arguments)
    read: bool
    leaves: list[Any] | None  # None: the call cannot be parsed, so it is never determinable

    def determinable(self, context: str) -> bool:
        return self.leaves is not None and all(h.leaf_present(leaf, context) for leaf in self.leaves)


@dataclass
class Turn(h.Message):
    read_call: bool = False  # every call of this tool turn is a read call


@dataclass
class Event:
    role: str  # user | assistant | tool
    text: str = ""
    calls: list[Call] = field(default_factory=list)
    name: str = ""  # tool events: the tool whose result this is
    usage: dict[str, int] | None = None  # assistant events: provider-reported usage, when present


def build_trajectory(events: list[Event], domain: str, model: str, task_id: Any, reward: float,
                     prefix_tokens: int) -> h.Trajectory:
    """PROTOCOL.md's transcript semantics (headroom.parse_trajectory), generalised to several calls per turn."""
    traj = h.Trajectory(domain, model, task_id, reward, prefix_tokens)
    context = run_context = ""
    in_run = seen_model_turn = False
    previous: Turn | None = None
    for e in events:
        if e.role == "assistant":
            msg = Turn("assistant", h.tokens(e.text))
            if not seen_model_turn:
                msg.key = "START"
            elif previous is not None and previous.role == "user":
                msg.key = "USER"
            elif previous is not None and previous.role == "tool":
                msg.key = f"TOOL:{previous.tool}"
            else:
                msg.key = "ASSISTANT"
            seen_model_turn = True
            if e.calls:
                msg.tool = e.calls[0].name
                msg.call_tokens = sum(h.tokens(c.name) + h.tokens(c.raw) for c in e.calls)
                msg.tokens += msg.call_tokens
                msg.determinable = all(c.determinable(context) for c in e.calls)
                msg.read_call = all(c.read for c in e.calls)
                if not in_run:
                    in_run, run_context, msg.first_of_run = True, context, True
                msg.determinable_before_run = all(c.determinable(run_context) for c in e.calls)
            else:
                in_run = False
        elif e.role == "tool":
            msg = Turn("tool", h.tokens(e.text), tool=e.name or (previous.tool if previous else "") or "")
            context += "\n" + e.text.lower()
        else:
            msg = Turn("user", h.tokens(e.text))
            context += "\n" + e.text.lower()
            in_run = False
        traj.messages.append(msg)
        previous = msg
    return traj


# ---------------------------------------------------------------- bash commands as tool calls
def bash_call(command: str, raw: str) -> Call:
    """Name, read-call flag and leaves of one bash call, per the amendment. Unparseable: not read, not determinable."""
    try:
        lexer = shlex.shlex(command, posix=True, punctuation_chars=True)
        lexer.whitespace_split = True
        words = list(lexer)
    except ValueError:
        return Call(_first_word(command), raw, False, None)
    segments: list[list[str]] = [[]]
    for w in words:
        if w in SEGMENT_OPS:
            segments.append([])
        else:
            segments[-1].append(w)
    segments = [s for s in segments if s]
    if not segments:
        return Call("", raw, False, None)
    redirect = any(w in REDIRECTS or w.startswith((">", ">>")) for w in words) or any(
        s[0] == "tee" for s in segments)
    programs, leaves = [], []
    for s in segments:
        width = 2 if s[0] == "git" and len(s) > 1 else 1
        program = " ".join(s[:width])
        programs.append((program, s))
        leaves += [w for w in s[width:] if not w.startswith("-") and w not in REDIRECTS]
    checked = [(p, s) for p, s in programs if p != "cd"]
    name = checked[0][0] if checked else "cd"
    read = bool(checked) and not redirect and all(_read_segment(p, s) for p, s in checked)
    return Call(name, raw, read, leaves)


def _read_segment(program: str, words: list[str]) -> bool:
    if program in READ_PROGRAMS or program in READ_GIT:
        return True
    if program == "sed":
        return "-n" in words and not any(w == "-i" or w.startswith("-i") for w in words[1:])
    return False


def _first_word(command: str) -> str:
    parts = command.split()
    return parts[0] if parts else ""


def read_name(domain: str, name: str) -> bool:
    """Can a D0 rule predict this name? τ²-bench: the PROTOCOL.md prefix rule. Coding: read-only programs."""
    if domain == CODING:
        return name in READ_PROGRAMS or name in READ_GIT or name == "sed"
    return h.is_read_tool(name)


# ---------------------------------------------------------------- τ²-bench
def tau2_tool_definitions(tools_root: Path) -> tuple[dict[str, int], dict[str, dict[str, str]]]:
    """Per domain: estimated tokens of the agent's tool definitions, and each tool's ToolType (parsed, never run)."""
    tokens_by_domain, types_by_domain = {}, {}
    for domain, (rel, sha) in TAU2_TOOLS.items():
        tree = ast.parse(_verify(tools_root / rel, sha).decode("utf-8"))
        total, types = 0, {}
        for fn in ast.walk(tree):
            if not isinstance(fn, ast.FunctionDef):
                continue
            tool_type = _is_tool(fn)
            if tool_type is None:
                continue
            params = [{"name": a.arg, "annotation": ast.unparse(a.annotation) if a.annotation else None}
                      for a in fn.args.args if a.arg != "self"]
            spec = {"name": fn.name, "description": ast.get_docstring(fn) or "", "parameters": params}
            total += h.tokens(json.dumps(spec, sort_keys=True))
            types[fn.name] = tool_type
        tokens_by_domain[domain], types_by_domain[domain] = total, types
    return tokens_by_domain, types_by_domain


def _is_tool(fn: ast.FunctionDef) -> str | None:
    for dec in fn.decorator_list:
        target = dec.func if isinstance(dec, ast.Call) else dec
        name = target.attr if isinstance(target, ast.Attribute) else getattr(target, "id", "")
        if name == "is_tool":
            if isinstance(dec, ast.Call) and dec.args and isinstance(dec.args[0], ast.Attribute):
                return dec.args[0].attr
            return "UNSPECIFIED"
    return None


def tau2_events(messages: list[dict[str, Any]]) -> list[Event]:
    """What the agent sees: its own turns, the results of its own calls, and the user's text messages."""
    events: list[Event] = []
    call_names: dict[Any, str] = {}
    for m in messages:
        role = m.get("role")
        if role == "assistant":
            calls = []
            for c in m.get("tool_calls") or []:
                args = c.get("arguments") or {}
                raw = args if isinstance(args, str) else json.dumps(args, sort_keys=True)
                name = str(c.get("name") or "")
                call_names[c.get("id")] = name
                calls.append(Call(name, raw, h.is_read_tool(name), h.leaves(args)))
            usage = m.get("usage") if isinstance(m.get("usage"), dict) else None
            events.append(Event("assistant", str(m.get("content") or ""), calls, usage=usage))
        elif role == "tool":
            if m.get("requestor") == "user":
                continue
            events.append(Event("tool", str(m.get("content") or ""), name=call_names.get(m.get("id"), "")))
        elif role == "user":
            if m.get("tool_calls"):
                continue
            events.append(Event("user", str(m.get("content") or "")))
    return events


def load_tau2(root: Path, tools_root: Path, split: str) -> tuple[list[h.Trajectory], dict[str, Any]]:
    tool_tokens, tool_types = tau2_tool_definitions(tools_root)
    out: list[h.Trajectory] = []
    calibration: dict[str, dict[str, list[float]]] = {d: {"input": [], "output": []} for d in TAU2_DOMAINS}
    for name, (domain, model, sha) in TAU2_FILES.items():
        data = json.loads(_verify(root / TAU2_DIR / name, sha))
        policy = str(((data.get("info") or {}).get("environment_info") or {}).get("policy") or "")
        prefix = h.tokens(policy) + tool_tokens[domain]
        for sim in data.get("simulations") or []:
            if h.split_of(domain, sim.get("task_id")) != split:
                continue
            reward = float(((sim.get("reward_info") or {}).get("reward")) or 0.0)
            events = tau2_events(sim.get("messages") or [])
            out.append(build_trajectory(events, domain, model, sim.get("task_id"), reward, prefix))
            if reward == 1:
                _calibrate(events, prefix, calibration[domain])
    agreement = {}
    for domain, types in tool_types.items():
        pairs = [(h.is_read_tool(n), t == "READ") for n, t in types.items()]
        agreement[domain] = {"tools": len(pairs), "agree": sum(a == b for a, b in pairs),
                             "prefix_read_not_typed_read": sorted(n for n, t in types.items()
                                                                  if h.is_read_tool(n) and t != "READ"),
                             "typed_read_not_prefix_read": sorted(n for n, t in types.items()
                                                                  if t == "READ" and not h.is_read_tool(n))}
    meta = {"tool_definition_tokens": tool_tokens, "read_tool_agreement_with_tooltype": agreement,
            "calibration": {d: {k: _spread(v) for k, v in c.items()} for d, c in calibration.items()}}
    return out, meta


def _calibrate(events: list[Event], prefix: int, sink: dict[str, list[float]]) -> None:
    running = prefix
    for e in events:
        if e.role == "assistant":
            billed = h.tokens(e.text) + sum(h.tokens(c.name) + h.tokens(c.raw) for c in e.calls)
            u = e.usage or {}
            if u.get("prompt_tokens"):
                sink["input"].append(running / u["prompt_tokens"])
            if u.get("completion_tokens"):
                sink["output"].append(billed / u["completion_tokens"])
            running += billed
        else:
            running += h.tokens(e.text)


def _spread(values: list[float]) -> dict[str, Any]:
    if not values:
        return {"n": 0, "median": None, "q1": None, "q3": None}
    values = sorted(values)
    q = statistics.quantiles(values, n=4) if len(values) > 1 else [values[0]] * 3
    return {"n": len(values), "median": h._round(statistics.median(values)), "q1": h._round(q[0]),
            "q3": h._round(q[2])}


# ---------------------------------------------------------------- TwinRouterBench
def load_twin(root: Path) -> tuple[list[dict[str, Any]], dict[str, str], dict[str, dict[str, float]]]:
    rows = [json.loads(line) for line in _verify(root / "data/static/question_bank.jsonl",
                                                  TWIN_FILES["data/static/question_bank.jsonl"]).decode().splitlines()
            if line.strip()]
    tiers = json.loads(_verify(root / "data/dynamic/tier_to_model.json",
                               TWIN_FILES["data/dynamic/tier_to_model.json"]))["map"]
    pricing = json.loads(_verify(root / "data/dynamic/model_pricing.json",
                                 TWIN_FILES["data/dynamic/model_pricing.json"]))["pricing"]
    return rows, tiers, pricing


def instances(rows: list[dict[str, Any]], benchmark: str) -> tuple[dict[str, list[dict[str, Any]]], list[str]]:
    """Complete step sequences per instance, and the ids of instances excluded as incomplete or inconsistent."""
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in rows:
        if r.get("benchmark") == benchmark:
            grouped[str(r.get("instance_id"))].append(r)
    complete, excluded = {}, []
    for iid, steps in sorted(grouped.items()):
        steps.sort(key=lambda r: r.get("step_index", 0))
        total = steps[0].get("total_steps")
        if [r.get("step_index") for r in steps] != list(range(1, (total or 0) + 1)) or not all(
                steps[k + 1]["messages"][:len(steps[k]["messages"])] == steps[k]["messages"]
                for k in range(len(steps) - 1)):
            excluded.append(iid)
            continue
        complete[iid] = steps
    return complete, excluded


def message_tokens(m: dict[str, Any]) -> int:
    n = h.tokens(str(m.get("content") or ""))
    for c in m.get("tool_calls") or []:
        fn = c.get("function") or {}
        args = fn.get("arguments")
        n += h.tokens(str(fn.get("name") or "")) + h.tokens(args if isinstance(args, str) else json.dumps(args))
    return n


def swe_trajectory(iid: str, steps: list[dict[str, Any]]) -> h.Trajectory:
    """The last step's messages, then the final model turn (output unknown: 0 tokens, never deleted)."""
    messages = steps[-1]["messages"]
    system = "".join(str(m.get("content") or "") for m in messages if m.get("role") == "system")
    events: list[Event] = []
    names: dict[Any, str] = {}
    for m in messages:
        role = m.get("role")
        if role == "system":
            continue
        if role == "assistant":
            calls = []
            for c in m.get("tool_calls") or []:
                fn = c.get("function") or {}
                raw = fn.get("arguments")
                raw = raw if isinstance(raw, str) else json.dumps(raw, sort_keys=True)
                try:
                    command = str((json.loads(raw) or {}).get("command") or "")
                except (ValueError, AttributeError):
                    command = ""
                call = bash_call(command, raw)
                names[c.get("id")] = call.name
                calls.append(call)
            events.append(Event("assistant", str(m.get("content") or ""), calls))
        elif role == "tool":
            events.append(Event("tool", str(m.get("content") or ""), name=names.get(m.get("tool_call_id"), "")))
        else:
            events.append(Event("user", str(m.get("content") or "")))
    events.append(Event("assistant", ""))  # the final model call; its output is not in the data
    return build_trajectory(events, CODING, "twinrouter-swe", iid, 1.0, h.tokens(system))


def load_coding(root: Path, split: str) -> tuple[list[h.Trajectory], dict[str, Any]]:
    rows, _, _ = load_twin(root)
    complete, excluded = instances(rows, "swebench")
    out = [swe_trajectory(iid, steps) for iid, steps in complete.items() if h.split_of(CODING, iid) == split]
    return out, {"instances_complete": len(complete), "instances_excluded": excluded}


# ---------------------------------------------------------------- tier ceiling
def tier_steps(steps: list[dict[str, Any]]) -> list[tuple[int, int, str]]:
    """(input tokens, output tokens, target tier) per labelled step; output 0 when not observed."""
    out = []
    for k, r in enumerate(steps):
        inp = sum(message_tokens(m) for m in r["messages"])
        if k + 1 < len(steps):
            new = steps[k + 1]["messages"][len(r["messages"]):]
            outp = sum(message_tokens(m) for m in new if m.get("role") == "assistant")
        else:
            outp = 0
        out.append((inp, outp, str(r.get("target_tier"))))
    return out


def tier_cost(steps: list[tuple[int, int, str]], tiers: dict[str, str], pricing: dict[str, dict[str, float]],
              *, all_high: bool) -> float:
    """USD of the steps, each at its target tier (or all at high), with per-model caching."""
    total, previous_model, previous_input = 0.0, None, None
    for inp, outp, tier in steps:
        model = tiers["high" if all_high else tier]
        p = pricing[model]
        same = previous_model == model and previous_input is not None
        read = previous_input if same and previous_input >= h.CARDS[h.PRIMARY_CARD].min_cacheable else 0
        fresh = max(p["input_per_m"], p["cache_write_per_m"])
        total += (inp - read) * fresh + read * p["cache_read_per_m"] + outp * p["output_per_m"]
        previous_model, previous_input = model, inp
    return total / 1_000_000


def tier_ceiling(root: Path, split: str) -> dict[str, Any]:
    rows, tiers, pricing = load_twin(root)
    out: dict[str, Any] = {}
    for bench in sorted({r.get("benchmark") for r in rows}):
        complete, excluded = instances(rows, bench)
        key = CODING if bench == "swebench" else f"twinrouter-{bench}"
        result: dict[str, Any] = {"instances_excluded": len(excluded)}
        observed_output = False
        for scope in ("split", "all"):
            chosen = {i: s for i, s in complete.items() if scope == "all" or h.split_of(key, i) == split}
            table = []
            for iid, steps in chosen.items():
                ts = tier_steps(steps)
                observed_output |= any(o > 0 for _, o, _ in ts)
                table.append({"task": iid, "cost": {"TIER": {"original": tier_cost(ts, tiers, pricing, all_high=True),
                                                             "tier": tier_cost(ts, tiers, pricing, all_high=False)}}})
            share = h.share_removed(table, "TIER", "tier") if table else None
            entry: dict[str, Any] = {"instances": len(table), "steps": sum(len(s) for s in chosen.values()),
                                     "share": h._round(share)}
            if scope == "split":
                interval = h.bootstrap_interval(table, "TIER", "tier") if table else None
                entry["interval"] = None if interval is None else [h._round(interval[0]), h._round(interval[1])]
                entry["tiers"] = dict(Counter(r.get("target_tier") for s in chosen.values() for r in s))
            result["split" if scope == "split" else "all_instances"] = entry
        result["input_only"] = not observed_output
        out[bench] = result
    return out


# ---------------------------------------------------------------- oracles on the new domains
def mine_rules(train: list[h.Trajectory], domains: tuple[str, ...]) -> dict[str, dict[str, dict[str, Any]]]:
    """headroom.mine_rules for any domain list, with the amendment's read-name predicate."""
    counts: dict[str, dict[str, Counter]] = {d: defaultdict(Counter) for d in domains}
    for traj in train:
        if traj.reward != 1 or traj.domain not in counts:
            continue
        for m in traj.messages:
            if m.is_model_turn:
                counts[traj.domain][m.key][m.tool or "REPLY"] += 1
    rules: dict[str, dict[str, dict[str, Any]]] = {d: {} for d in domains}
    for domain, by_key in counts.items():
        for key, actions in by_key.items():
            support = sum(actions.values())
            action, n = actions.most_common(1)[0]
            if support >= h.RULE_MIN_SUPPORT and n / support >= h.RULE_MIN_SHARE and read_name(domain, action):
                rules[domain][key] = {"tool": action, "support": support, "share": round(n / support, 4)}
    return rules


def selections(traj: h.Trajectory, rules: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """headroom.selections, with D0 requiring a read call (every call of the turn) instead of a read name."""
    d2, d1, d0 = set(), set(), set()
    merged: dict[int, int] = {}
    fires = 0
    run_first: int | None = None
    for index, m in enumerate(traj.messages):
        if m.role == "user" or (m.is_model_turn and not m.is_tool_turn):
            run_first = None
        if not m.is_model_turn:
            continue
        rule = rules.get(m.key)
        if rule is not None:
            fires += 1
        if not m.is_tool_turn:
            continue
        d2.add(index)
        if m.determinable:
            d1.add(index)
            if rule is not None and rule["tool"] == m.tool and getattr(m, "read_call", False):
                d0.add(index)
        if m.first_of_run or run_first is None:
            run_first = index
        elif m.determinable_before_run:
            merged[index] = run_first
    return {"D2": frozenset(d2), "D1": frozenset(d1), "D0": frozenset(d0), "batching": merged,
            "d0_fires": fires, "d0_correct": len(d0)}


def analyse(trajectories: list[h.Trajectory], rules: dict[str, dict[str, dict[str, Any]]]) -> list[dict[str, Any]]:
    """headroom.analyse with this module's selections; rows have the same shape, so headroom.summarise applies."""
    rows = []
    for traj in trajectories:
        sel = selections(traj, rules.get(traj.domain, {}))
        row: dict[str, Any] = {
            "domain": traj.domain, "model": traj.model, "task": f"{traj.domain}:{traj.task_id}",
            "reward": traj.reward, "model_turns": sum(1 for m in traj.messages if m.is_model_turn),
            "d0_fires": sel["d0_fires"], "d0_correct": sel["d0_correct"],
            "deleted": {o: len(sel[o]) for o in h.ORACLES},
            "d1_tools": Counter(traj.messages[i].tool for i in sel["D1"]), "cost": {}}
        for name, card in h.CARDS.items():
            row["cost"][name] = {"original": h.cost(traj, card)}
            for oracle in ("D2", "D1", "D0"):
                row["cost"][name][oracle] = h.cost(traj, card, deleted=sel[oracle])
            row["cost"][name]["batching"] = h.cost(traj, card, merged=sel["batching"])
        rows.append(row)
    return rows


def grouped(rows: list[dict[str, Any]], key: Callable[[dict[str, Any]], str], *, intervals: bool) -> dict[str, Any]:
    out: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in rows:
        out[key(r)].append(r)
    return {k: h.summarise(v, intervals=intervals) for k, v in sorted(out.items())}


# ---------------------------------------------------------------- the combined decision rule
def verdict(noncoding: dict[str, dict[str, float | None]], coding: dict[str, dict[str, float | None]]
            ) -> tuple[str, str]:
    """PROTOCOL-AMENDMENT-1.md's rule on P1 point estimates, in its stated order."""
    usable_new = [d for d in (*TAU2_DOMAINS, CODING) if d in noncoding or d in coding]
    if not usable_new:
        return "INCONCLUSIVE", "neither added dataset could be used as specified"
    every = {**noncoding, **coding}
    if any(v is None for d in every.values() for v in d.values()):
        return "INCONCLUSIVE", "a share could not be computed for every domain"
    if all(v["D1"] < h.THRESHOLD for v in noncoding.values()) and all(v["D1"] < h.THRESHOLD
                                                                         for v in coding.values()) and coding:
        return "STOP", "D1 removes less than 15% in every non-coding domain and on the coding set"
    if all(v["batching"] >= v["D0"] for v in every.values()):
        return "SHRINK", "in every domain, coding included, the batching ceiling is at least as large as D0"
    winners = [d for d, v in noncoding.items() if v["D0"] >= h.THRESHOLD and v["D0"] > v["batching"]]
    if winners:
        return "PROCEED", f"D0 removes at least 15% and exceeds the batching ceiling in: {', '.join(winners)}"
    return "HOLD", "no non-coding domain has D0 at or above 15% and above the batching ceiling"


def p1(summary: dict[str, Any]) -> dict[str, float | None]:
    return {o: summary["oracles"][o]["cost_share"][h.PRIMARY_CARD] for o in ("D1", "D0", "batching")}


# ---------------------------------------------------------------- report
def build_report(tau2_root: Path, tools_root: Path, twin_root: Path, split: str,
                 results_json: Path = _HERE / "results.json") -> dict[str, Any]:
    tau2_train, tau2_meta = load_tau2(tau2_root, tools_root, "train")
    coding_train, coding_meta = load_coding(twin_root, "train")
    rules = {**mine_rules(tau2_train, TAU2_DOMAINS), **mine_rules(coding_train, (CODING,))}
    if split == "train":
        tau2, coding = tau2_train, coding_train
    else:
        tau2, tau2_meta = load_tau2(tau2_root, tools_root, split)
        coding, coding_meta = load_coding(twin_root, split)
    tau2_rows, coding_rows = analyse(tau2, rules), analyse(coding, rules)
    primary_tau2 = [r for r in tau2_rows if r["reward"] == 1]
    primary_coding = [r for r in coding_rows if r["reward"] == 1]
    by_domain = grouped(primary_tau2, lambda r: r["domain"], intervals=True)
    coding_summary = grouped(primary_coding, lambda r: r["domain"], intervals=True)
    frozen = json.loads(results_json.read_text(encoding="utf-8"))
    tau_bench = {d: frozen["primary"]["by_domain"][d] for d in TAU_BENCH_DOMAINS}
    noncoding = {**{d: p1(s) for d, s in tau_bench.items()}, **{d: p1(s) for d, s in by_domain.items()}}
    coding_p1 = {d: p1(s) for d, s in coding_summary.items()}
    name, reason = verdict(noncoding, coding_p1)
    return {
        "schema": "turnwise.stage0-amendment-1/1",
        "protocol": "research/stage0_headroom/PROTOCOL-AMENDMENT-1.md",
        "split": split,
        "data": {"tau2_commit": TAU2_COMMIT, "tau2_tools_tag": TAU2_TOOLS_TAG, "twinrouter_commit": TWIN_COMMIT},
        "tau2": {"meta": tau2_meta, "rules": {d: rules[d] for d in TAU2_DOMAINS},
                 "primary": {"by_domain": by_domain,
                             "by_file": grouped(primary_tau2, lambda r: f"{r['domain']}/{r['model']}", intervals=True)},
                 "secondary_all_trajectories": {d: {o: s["oracles"][o]["cost_share"][h.PRIMARY_CARD]
                                                    for o in h.ORACLES}
                                                for d, s in grouped(tau2_rows, lambda r: r["domain"],
                                                                    intervals=False).items()}},
        "coding": {"meta": coding_meta, "rules": rules[CODING], "primary": coding_summary},
        "tier_ceiling": tier_ceiling(twin_root, split),
        "combined": {"tau_bench_from_results_json": {d: p1(s) for d, s in tau_bench.items()},
                     "noncoding_p1": noncoding, "coding_p1": coding_p1, "verdict": name, "reason": reason},
    }


def render(report: dict[str, Any]) -> str:
    pct = h._pct
    lines = [f"Stage 0 amendment 1, {report['split']} split (primary analysis set, P1 shares of estimated cost)", ""]
    for title, block in (("τ²-bench", report["tau2"]["primary"]["by_domain"]), ("coding", report["coding"]["primary"])):
        lines.append(f"{title}:")
        for d, s in block.items():
            o = s["oracles"]
            lines.append(f"  {d:14} n={s['trajectories']:4} tasks={s['tasks']:3}  "
                         + "  ".join(f"{k} {pct(o[k]['cost_share']['P1'])}" for k in h.ORACLES))
    lines.append(f"tier ceiling (TwinRouterBench prices, {report['split']} split by instance):")
    for b, t in report["tier_ceiling"].items():
        lines.append(f"  {b:12} instances={t['split']['instances']:3} share {pct(t['split']['share'])}"
                     + ("  (input only)" if t["input_only"] else ""))
    c = report["combined"]
    lines += ["", f"VERDICT: {c['verdict']} ({c['reason']})"]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--tau2-root", required=True, type=Path, help=f"tau2-bench at {TAU2_COMMIT}")
    p.add_argument("--tau2-tools-root", required=True, type=Path, help=f"tau2-bench at tag {TAU2_TOOLS_TAG}")
    p.add_argument("--twinrouter-root", required=True, type=Path, help=f"TwinRouterBench at {TWIN_COMMIT}")
    p.add_argument("--split", required=True, choices=("train", "eval"))
    p.add_argument("--json-out", type=Path)
    args = p.parse_args(argv)
    report = build_report(args.tau2_root, args.tau2_tools_root, args.twinrouter_root, args.split)
    print(render(report))
    if args.json_out:
        args.json_out.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
