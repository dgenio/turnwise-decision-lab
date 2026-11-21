"""Stage 0 headroom analysis on public agent trajectories (issue #86). Stdlib only; calls no model.

Implements research/stage0_headroom/PROTOCOL.md exactly: read that file first. This script reads the tau-bench
historical trajectories from a local clone, re-costs each trajectory under a cache-aware price card, and reports
how much of that cost hindsight oracles could remove by deleting model turns.

    python -I research/stage0_headroom/headroom.py --tau-bench-root /path/to/tau-bench --split train
    python -I research/stage0_headroom/headroom.py --tau-bench-root /path/to/tau-bench --split eval \
        --json-out research/stage0_headroom/results.json

The trajectory files are third-party data: the script only parses JSON and Python *literals* (``ast``), never
imports or executes anything from the clone, and is meant to be run with ``python -I``.
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
import math
import random
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

DATA_COMMIT = "59a200c6d575d595120f1cb70fea53cef0632f6b"
FILES = {  # file -> (domain, model, sha256)
    "gpt-4o-airline.json": ("airline", "gpt-4o", "e9e6c0297660c537f83d4fd9c476ce7a9a86ecd2784874b7bfc13be598e37bfa"),
    "gpt-4o-retail.json": ("retail", "gpt-4o", "df01707894836168ff0ec9616b0bf08f66c7e5afcf313e5fe4f7a2f5c2ec938b"),
    "sonnet-35-new-airline.json": ("airline", "sonnet-35-new",
                                   "fe62fcd514b855b36f156dd4c3c7748597b392b006aff739b53337a9f3ba94d1"),
    "sonnet-35-new-retail.json": ("retail", "sonnet-35-new",
                                  "0df526398e9d2720c32d340815cffb04fe8c4f8a61b1f4f84bf3bb558f760131"),
}
DOMAINS = ("airline", "retail")
READ_PREFIXES = ("get_", "find_", "list_", "search_")
ORACLES = ("D2", "D1", "D0", "batching")


@dataclass(frozen=True)
class Card:
    fresh: float
    cached: float
    output: float
    min_cacheable: int
    lapse_at_user: bool = False


CARDS = {"P1": Card(2.50, 0.10, 10.00, 1024), "P2": Card(2.00, 0.20, 10.00, 1024),
         "P3": Card(2.00, 2.00, 10.00, 0), "P4": Card(2.50, 0.10, 10.00, 1024, lapse_at_user=True)}
PRIMARY_CARD = "P1"
RULE_MIN_SUPPORT, RULE_MIN_SHARE = 20, 0.90
THRESHOLD = 0.15
BOOTSTRAP_RESAMPLES, BOOTSTRAP_SEED = 2000, 86


# ---------------------------------------------------------------- basics
def tokens(text: str | None) -> int:
    """The protocol's estimator: ceil(characters / 4)."""
    return math.ceil(len(text or "") / 4)


def split_of(domain: str, task_id: Any) -> str:
    digest = hashlib.sha256(f"{domain}:{task_id}".encode()).hexdigest()
    return "train" if int(digest[:8], 16) % 2 == 0 else "eval"


def is_read_tool(name: str | None) -> bool:
    return bool(name) and name.startswith(READ_PREFIXES)


def leaves(value: Any) -> list[Any]:
    """Scalar values of the arguments after flattening lists and objects."""
    if isinstance(value, dict):
        return [leaf for v in value.values() for leaf in leaves(v)]
    if isinstance(value, (list, tuple)):
        return [leaf for v in value for leaf in leaves(v)]
    return [value]


def leaf_present(leaf: Any, context: str) -> bool:
    """Is this argument leaf present (case-insensitive substring) in the lower-cased context?"""
    if leaf is None or isinstance(leaf, bool):
        return True
    if isinstance(leaf, float) and leaf.is_integer():
        return str(leaf).lower() in context or str(int(leaf)) in context
    return str(leaf).lower() in context


def determinable(arguments: Any, context: str) -> bool:
    return all(leaf_present(leaf, context) for leaf in leaves(arguments))


# ---------------------------------------------------------------- tool definitions (parsed, never executed)
def tool_definition_tokens(root: Path, domain: str) -> tuple[int, list[str]]:
    """Tokens of the domain's tool definitions, from the literal each tool's ``get_info()`` returns."""
    total, problems = 0, []
    directory = root / "tau_bench" / "envs" / domain / "tools"
    for path in sorted(directory.glob("*.py")):
        if path.name == "__init__.py":
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
            returns = [node.value for fn in ast.walk(tree)
                       if isinstance(fn, ast.FunctionDef) and fn.name == "get_info"
                       for node in ast.walk(fn) if isinstance(node, ast.Return) and node.value is not None]
            info = ast.literal_eval(returns[0])
            total += tokens(json.dumps(info, sort_keys=True))
        except (OSError, SyntaxError, ValueError, IndexError) as exc:
            problems.append(f"{domain}/{path.name}: {type(exc).__name__}")
    return total, problems


# ---------------------------------------------------------------- trajectories
@dataclass
class Message:
    role: str
    tokens: int  # as it stands in the original transcript
    call_tokens: int = 0  # assistant tool turns: the tool call alone (name + arguments)
    tool: str | None = None  # assistant tool turns: tool name
    key: str = ""  # model turns: START, USER, TOOL:<name> or ASSISTANT
    determinable: bool = False  # tool turns: call determinable from earlier user messages and tool results
    determinable_before_run: bool = False  # ... from the context before the first turn of its run
    first_of_run: bool = False

    @property
    def is_model_turn(self) -> bool:
        return self.role == "assistant"

    @property
    def is_tool_turn(self) -> bool:
        return self.role == "assistant" and self.tool is not None


@dataclass
class Trajectory:
    domain: str
    model: str
    task_id: Any
    reward: float
    prefix_tokens: int
    messages: list[Message] = field(default_factory=list)


def _first_call(message: dict[str, Any]) -> tuple[str, Any, str] | None:
    """(tool name, parsed arguments, raw arguments text) of the message's first tool call, if it has one."""
    calls = message.get("tool_calls") or []
    if not calls or not isinstance(calls[0], dict):
        return None
    fn = calls[0].get("function") or {}
    raw = fn.get("arguments")
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
        except ValueError:
            parsed = raw
    else:
        parsed, raw = raw, json.dumps(raw, sort_keys=True)
    return str(fn.get("name") or ""), parsed, raw or ""


def parse_trajectory(record: dict[str, Any], domain: str, model: str, tools_tokens: int) -> Trajectory:
    raw = [m for m in record.get("traj") or [] if isinstance(m, dict)]
    system = "".join(str(m.get("content") or "") for m in raw if m.get("role") == "system")
    traj = Trajectory(domain, model, record.get("task_id"), float(record.get("reward") or 0.0),
                      tokens(system) + tools_tokens)
    context = ""  # lower-cased user messages and tool results seen so far
    run_context = ""  # context before the first turn of the current run of tool turns
    in_run = False
    previous: Message | None = None
    seen_model_turn = False
    for m in raw:
        role = m.get("role")
        if role == "system":
            continue
        content = str(m.get("content") or "")
        if role == "assistant":
            call = _first_call(m)
            msg = Message("assistant", tokens(content))
            if not seen_model_turn:
                msg.key = "START"
            elif previous is not None and previous.role == "user":
                msg.key = "USER"
            elif previous is not None and previous.role == "tool":
                msg.key = f"TOOL:{previous.tool}"
            else:
                msg.key = "ASSISTANT"
            seen_model_turn = True
            if call is not None:
                name, arguments, raw_args = call
                msg.tool = name
                msg.call_tokens = tokens(name) + tokens(raw_args)
                msg.tokens += msg.call_tokens
                msg.determinable = determinable(arguments, context)
                if not in_run:
                    in_run, run_context, msg.first_of_run = True, context, True
                msg.determinable_before_run = determinable(arguments, run_context)
            else:
                in_run = False
        elif role == "tool":
            msg = Message("tool", tokens(content), tool=str(m.get("name") or (previous.tool if previous else "") or ""))
            context += "\n" + content.lower()
        else:  # user (anything else is treated as user-visible input)
            msg = Message("user", tokens(content))
            context += "\n" + content.lower()
            in_run = False
        traj.messages.append(msg)
        previous = msg
    return traj


def load(root: Path, split: str) -> tuple[list[Trajectory], dict[str, Any]]:
    """Every trajectory of ``split`` from the four pinned files. Refuses a file whose hash differs."""
    directory = root / "historical_trajectories"
    tools, problems = {}, []
    for domain in DOMAINS:
        tools[domain], issues = tool_definition_tokens(root, domain)
        problems += issues
    out: list[Trajectory] = []
    for name, (domain, model, expected) in FILES.items():
        data = (directory / name).read_bytes()
        actual = hashlib.sha256(data).hexdigest()
        if actual != expected:
            raise SystemExit(f"{name}: SHA-256 {actual} does not match the protocol ({expected}); refusing to run")
        for record in json.loads(data):
            if split_of(domain, record.get("task_id")) == split:
                out.append(parse_trajectory(record, domain, model, tools[domain]))
    return out, {"tool_definition_tokens": tools, "tool_definition_problems": problems}


# ---------------------------------------------------------------- cost model
def cost(traj: Trajectory, card: Card, deleted: frozenset[int] = frozenset(),
         merged: dict[int, int] | None = None) -> float:
    """USD (per the card, in millionths) of the agent's model turns, with some turns deleted or merged.

    ``deleted``: message indices of model turns that are not model calls any more. Their tool call stays in the
    transcript (the host runs it), so only its call tokens count toward later inputs. ``merged``: message index
    of a tool turn -> index of the turn whose response now carries its call (the batching ceiling); a merged turn
    is deleted as a call and its call tokens are billed as output of the turn it joins.
    """
    merged = merged or {}
    gone = deleted | frozenset(merged)
    extra_output: dict[int, int] = defaultdict(int)
    for index, target in merged.items():
        extra_output[target] += traj.messages[index].call_tokens
    total = 0.0
    running = traj.prefix_tokens  # tokens of everything before the current message
    previous_input: int | None = None
    user_since_previous = False
    for index, m in enumerate(traj.messages):
        if m.is_model_turn and index not in gone:
            read = previous_input if previous_input is not None and previous_input >= card.min_cacheable else 0
            if card.lapse_at_user and user_since_previous:
                read = 0
            output = m.tokens + extra_output.get(index, 0)
            total += (running - read) * card.fresh + read * card.cached + output * card.output
            previous_input, user_since_previous = running, False
        if m.role == "user":
            user_since_previous = True
        running += m.call_tokens if index in gone else m.tokens
    return total / 1_000_000


# ---------------------------------------------------------------- oracles
def mine_rules(train: list[Trajectory]) -> dict[str, dict[str, dict[str, Any]]]:
    """D0 rules per domain: key -> {tool, support, share}, from reward-1 train trajectories, models pooled."""
    counts: dict[str, dict[str, Counter]] = {d: defaultdict(Counter) for d in DOMAINS}
    for traj in train:
        if traj.reward != 1:
            continue
        for m in traj.messages:
            if m.is_model_turn:
                counts[traj.domain][m.key][m.tool or "REPLY"] += 1
    rules: dict[str, dict[str, dict[str, Any]]] = {d: {} for d in DOMAINS}
    for domain, by_key in counts.items():
        for key, actions in by_key.items():
            support = sum(actions.values())
            action, n = actions.most_common(1)[0]
            if support >= RULE_MIN_SUPPORT and n / support >= RULE_MIN_SHARE and is_read_tool(action):
                rules[domain][key] = {"tool": action, "support": support, "share": round(n / support, 4)}
    return rules


def selections(traj: Trajectory, rules: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """What each oracle deletes in this trajectory, plus D0 fire counts."""
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
            if rule is not None and rule["tool"] == m.tool and is_read_tool(m.tool):
                d0.add(index)
        if m.first_of_run or run_first is None:
            run_first = index
        elif m.determinable_before_run:
            merged[index] = run_first
    return {"D2": frozenset(d2), "D1": frozenset(d1), "D0": frozenset(d0), "batching": merged,
            "d0_fires": fires, "d0_correct": len(d0)}


# ---------------------------------------------------------------- aggregation
def analyse(trajectories: list[Trajectory], rules: dict[str, dict[str, dict[str, Any]]]) -> list[dict[str, Any]]:
    """One row per trajectory: original and per-oracle cost under every card, and turn counts."""
    rows = []
    for traj in trajectories:
        sel = selections(traj, rules[traj.domain])
        row: dict[str, Any] = {
            "domain": traj.domain, "model": traj.model, "task": f"{traj.domain}:{traj.task_id}",
            "reward": traj.reward, "model_turns": sum(1 for m in traj.messages if m.is_model_turn),
            "d0_fires": sel["d0_fires"], "d0_correct": sel["d0_correct"],
            "deleted": {o: len(sel[o]) for o in ORACLES},
            "d1_tools": Counter(traj.messages[i].tool for i in sel["D1"]),
            "cost": {}}
        for name, card in CARDS.items():
            row["cost"][name] = {"original": cost(traj, card)}
            for oracle in ("D2", "D1", "D0"):
                row["cost"][name][oracle] = cost(traj, card, deleted=sel[oracle])
            row["cost"][name]["batching"] = cost(traj, card, merged=sel["batching"])
        rows.append(row)
    return rows


def share_removed(rows: list[dict[str, Any]], card: str, oracle: str) -> float | None:
    original = sum(r["cost"][card]["original"] for r in rows)
    return None if original <= 0 else 1 - sum(r["cost"][card][oracle] for r in rows) / original


def bootstrap_interval(rows: list[dict[str, Any]], card: str, oracle: str) -> tuple[float, float] | None:
    """95% percentile interval for the share removed, resampling tasks with replacement."""
    by_task: dict[str, list[float]] = defaultdict(lambda: [0.0, 0.0])
    for r in rows:
        by_task[r["task"]][0] += r["cost"][card]["original"]
        by_task[r["task"]][1] += r["cost"][card][oracle]
    tasks = sorted(by_task)
    if len(tasks) < 2:
        return None
    rng = random.Random(BOOTSTRAP_SEED)
    shares = []
    for _ in range(BOOTSTRAP_RESAMPLES):
        original = after = 0.0
        for _ in tasks:
            o, a = by_task[tasks[rng.randrange(len(tasks))]]
            original += o
            after += a
        if original > 0:
            shares.append(1 - after / original)
    shares.sort()
    return shares[int(0.025 * len(shares))], shares[min(int(0.975 * len(shares)), len(shares) - 1)]


def summarise(rows: list[dict[str, Any]], *, intervals: bool) -> dict[str, Any]:
    turns = sum(r["model_turns"] for r in rows)
    out: dict[str, Any] = {"trajectories": len(rows), "tasks": len({r["task"] for r in rows}),
                           "model_turns": turns, "oracles": {}}
    for oracle in ORACLES:
        deleted = sum(r["deleted"][oracle] for r in rows)
        entry: dict[str, Any] = {"turns_deleted": deleted,
                                 "turn_share": None if not turns else round(deleted / turns, 4),
                                 "cost_share": {c: _round(share_removed(rows, c, oracle)) for c in CARDS}}
        if intervals:
            interval = bootstrap_interval(rows, PRIMARY_CARD, oracle)
            entry["cost_share_interval_P1"] = None if interval is None else [_round(interval[0]), _round(interval[1])]
        out["oracles"][oracle] = entry
    fires, correct = sum(r["d0_fires"] for r in rows), sum(r["d0_correct"] for r in rows)
    out["d0_fires"] = {"fires": fires, "correct": correct,
                       "false_fire_rate": None if not fires else round(1 - correct / fires, 4)}
    tools: Counter = Counter()
    for r in rows:
        tools.update(r["d1_tools"])
    out["d1_top_tools"] = tools.most_common(10)
    return out


def verdict(per_domain: dict[str, dict[str, Any]]) -> tuple[str, str]:
    """The protocol's decision rule on P1 point estimates of the primary analysis set, in its stated order."""
    def share(domain: str, oracle: str) -> float | None:
        return per_domain[domain]["oracles"][oracle]["cost_share"][PRIMARY_CARD]

    values = {d: {o: share(d, o) for o in ("D1", "D0", "batching")} for d in per_domain}
    if not values or any(v is None for d in values.values() for v in d.values()):
        return "INCONCLUSIVE", "the non-coding data could not be used as specified"
    if all(v["D1"] < THRESHOLD for v in values.values()):
        return "STOP pending a coding set", "the liberal oracle D1 removes less than 15% in every domain"
    if all(v["batching"] >= v["D0"] for v in values.values()):
        return "SHRINK", "in every domain the batching ceiling is at least as large as D0"
    winners = [d for d, v in values.items() if v["D0"] >= THRESHOLD and v["D0"] > v["batching"]]
    if winners:
        return "PROCEED", f"D0 removes at least 15% and exceeds the batching ceiling in: {', '.join(winners)}"
    return "HOLD", "no domain has D0 at or above 15% and above the batching ceiling, and D1 clears 15% somewhere"


def _round(value: float | None) -> float | None:
    return None if value is None else round(value, 4)


# ---------------------------------------------------------------- report
def build_report(root: Path, split: str) -> dict[str, Any]:
    train, meta = load(root, "train")
    rules = mine_rules(train)
    trajectories = train if split == "train" else load(root, split)[0]
    rows = analyse(trajectories, rules)
    primary = [r for r in rows if r["reward"] == 1]
    report: dict[str, Any] = {
        "protocol": "research/stage0_headroom/PROTOCOL.md", "data_commit": DATA_COMMIT, "split": split,
        "token_estimator": "ceil(characters / 4)", "real_inference": False,
        "cards": {name: vars(card) for name, card in CARDS.items()}, "meta": meta, "rules": rules,
        "primary": {"definition": f"{split}-split trajectories with reward == 1",
                    "by_domain": {d: summarise([r for r in primary if r["domain"] == d], intervals=True)
                                  for d in DOMAINS},
                    "by_file": {f"{model}-{domain}": summarise(
                        [r for r in primary if r["domain"] == domain and r["model"] == model], intervals=True)
                        for domain, model, _ in FILES.values()}},
        "secondary": {"definition": f"all {split}-split trajectories",
                      "by_domain": {d: summarise([r for r in rows if r["domain"] == d], intervals=False)
                                    for d in DOMAINS}},
    }
    report["verdict"], report["verdict_reason"] = verdict(report["primary"]["by_domain"])
    return report


def _pct(value: float | None) -> str:
    return "unknown" if value is None else f"{100 * value:.1f}%"


def render(report: dict[str, Any]) -> str:
    lines = [f"split: {report['split']} | data: sierra-research/tau-bench @ {report['data_commit'][:7]} | "
             f"tokens: {report['token_estimator']} (estimate) | no model called", ""]
    for scope in ("by_domain", "by_file"):
        for name, s in report["primary"][scope].items():
            lines.append(f"[{report['primary']['definition']}] {name}: {s['trajectories']} trajectories, "
                         f"{s['tasks']} tasks, {s['model_turns']} model turns")
            for oracle in ORACLES:
                o = s["oracles"][oracle]
                interval = o.get("cost_share_interval_P1")
                lines.append(
                    f"    {oracle:<9} turns deleted {_pct(o['turn_share']):>7} | cost removed P1 "
                    f"{_pct(o['cost_share']['P1']):>7}"
                    + (f" [{_pct(interval[0])}, {_pct(interval[1])}]" if interval else "")
                    + f" | P2 {_pct(o['cost_share']['P2'])} | P3 {_pct(o['cost_share']['P3'])}"
                    f" | P4 {_pct(o['cost_share']['P4'])}")
            f = s["d0_fires"]
            lines.append(f"    D0 fires {f['fires']}, correct {f['correct']}, false-fire rate {_pct(f['false_fire_rate'])}")
        lines.append("")
    for domain, rules in report["rules"].items():
        listed = ", ".join(f"{k} -> {r['tool']} ({r['share']:.0%} of {r['support']})" for k, r in sorted(rules.items()))
        lines.append(f"D0 rules, {domain}: {listed or 'none'}")
    lines += ["", f"VERDICT: {report['verdict']} ({report['verdict_reason']})"]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--tau-bench-root", required=True, type=Path, help="local clone of sierra-research/tau-bench")
    p.add_argument("--split", required=True, choices=("train", "eval"))
    p.add_argument("--json-out", type=Path)
    args = p.parse_args(argv)
    report = build_report(args.tau_bench_root, args.split)
    print(render(report))
    if args.json_out:
        args.json_out.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
