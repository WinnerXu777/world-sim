"""Measure which ``instincts_and_tools`` functions the test suite actually calls (WS-H P0, plan finding 11).

    .venv/Scripts/python.exe at_the_beginning/harness/coverage_map.py [--pattern 'test_*.py'] [--json .runtime/coverage-iat.json]
                                                                      [--md 1008_coverage_map.md]

``coverage.py`` is not installed in the venv, so this is a tracing shim on ``sys.monitoring`` (Python 3.12+): it records every
call to a top-level function of ``instincts_and_tools.py``, how it was reached (a test calling it directly, through
``Engine.step``, or through another module), and which test modules reached it. It measures *calls*, not lines: a function
that is called but whose branches are mostly untested still counts as exercised. It runs the whole suite in one process, so
take the full-suite lock first (``.runtime/fullsuite.lock``).
"""
from __future__ import annotations

import argparse
import ast
import json
import sys
import time
import unittest
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
IAT = ROOT / "at_the_beginning" / "instincts_and_tools.py"
TESTS = ROOT / "tests"
TOOL_ID = 4


def declared_functions():
    tree = ast.parse(IAT.read_text(encoding="utf-8"))
    return {n.name: n.lineno for n in tree.body if isinstance(n, ast.FunctionDef)}


def registry_names():
    """Names listed in ``default_registry_entries`` (per-tick registry), read from source."""
    tree = ast.parse(IAT.read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == "default_registry_entries":
            return {n.id for n in ast.walk(node) if isinstance(n, ast.Name)}
    return set()


class Recorder:
    def __init__(self, names):
        self.names = set(names)
        self.calls = defaultdict(int)
        self.how = defaultdict(set)
        self.tests = defaultdict(set)
        self.current_test = "<import/setup>"
        self.iat_path = str(IAT).lower()
        self.tests_dir = str(TESTS).lower()

    def on_start(self, code, offset):
        if code.co_name not in self.names or code.co_filename.lower() != self.iat_path:
            return sys.monitoring.DISABLE   # stop being called for this code object: keeps the full-suite run fast
        name = code.co_name
        self.calls[name] += 1
        self.tests[name].add(self.current_test.split(".")[0] if "." in self.current_test else self.current_test)
        if self.calls[name] > 6 and len(self.how[name]) >= 2:
            return
        frame, in_step, first = sys._getframe(2), False, None  # frame 1 is the callee; frame 2 its caller
        depth = 0
        while frame is not None and depth < 60:
            filename = frame.f_code.co_filename.lower()
            if first is None and filename != self.iat_path:
                first = filename
            if frame.f_code.co_name == "step" and filename.endswith("map_test.py"):
                in_step = True
            frame, depth = frame.f_back, depth + 1
        if first is None:
            self.how[name].add("internal (called by another iat function only)")
        elif first.startswith(self.tests_dir):
            self.how[name].add("direct from a test")
        elif in_step:
            self.how[name].add("via Engine.step")
        else:
            self.how[name].add("via " + Path(first).name)


def run(pattern):
    functions = declared_functions()
    recorder = Recorder(functions)
    mon = sys.monitoring
    mon.use_tool_id(TOOL_ID, "iat-coverage")
    mon.register_callback(TOOL_ID, mon.events.PY_START, recorder.on_start)

    class Result(unittest.TextTestResult):
        def startTest(self, test):
            recorder.current_test = test.id().split(".")[0]
            super().startTest(test)

    sys.path.insert(0, str(TESTS))
    suite = unittest.defaultTestLoader.discover(str(TESTS), pattern=pattern)
    started = time.perf_counter()
    mon.set_events(TOOL_ID, mon.events.PY_START)   # after discovery: tracing torch's import crashed the interpreter (c10 abort)
    result = unittest.TextTestRunner(resultclass=Result, verbosity=0).run(suite)
    elapsed = time.perf_counter() - started
    mon.set_events(TOOL_ID, 0)
    mon.free_tool_id(TOOL_ID)
    return functions, recorder, result, elapsed


def report(functions, recorder, result, elapsed):
    registry = registry_names()
    rows = []
    for name, line in sorted(functions.items(), key=lambda kv: kv[1]):
        kind = "instinct" if name.startswith("instinct_") else "tool" if name.startswith("tool_") else "other"
        rows.append({"name": name, "line": line, "kind": kind, "registry": name in registry, "calls": recorder.calls.get(name, 0),
                     "how": sorted(recorder.how.get(name, [])), "test_modules": sorted(recorder.tests.get(name, []))})
    return {"suite": {"tests": result.testsRun, "failures": len(result.failures), "errors": len(result.errors), "seconds": round(elapsed, 1)},
            "functions": rows}


def markdown(data):
    rows = data["functions"]
    out = ["# 1008 coverage map: which legacy instincts and tools the tests exercise", "",
           f"Measured by `at_the_beginning/harness/coverage_map.py` (a `sys.monitoring` call tracer, because `coverage.py` is not installed) over the full suite: "
           f"{data['suite']['tests']} tests, {data['suite']['failures']} failures, {data['suite']['errors']} errors, {data['suite']['seconds']} s. "
           "\"Exercised\" means the function was **called** at least once; it says nothing about branch coverage or whether the result was asserted. "
           "Test modules listed are those whose tests were running when the call happened (setup/teardown included).", ""]
    for kind, title, total in (("instinct", "`instinct_*`", 46), ("tool", "`tool_*`", 74)):
        subset = [r for r in rows if r["kind"] == kind]
        hit = [r for r in subset if r["calls"]]
        direct = [r for r in hit if "direct from a test" in r["how"]]
        step = [r for r in hit if "via Engine.step" in r["how"]]
        out += [f"## {title}: {len(hit)} of {len(subset)} called by some test", "",
                f"- called directly from a test: {len(direct)}; reached through `Engine.step`: {len(step)}; never called: {len(subset) - len(hit)}"
                + ("" if len(subset) == total else f" (expected {total} declared; found {len(subset)})"), ""]
    other = [r for r in rows if r["kind"] == "other"]
    out += [f"## Other top-level functions in the module ({sum(1 for r in other if r['calls'])} of {len(other)} called)", ""]
    out += ["| function | registry | calls | how reached | test modules |", "| --- | --- | --- | --- | --- |"]
    for r in rows:
        if r["kind"] != "other" or r["name"].startswith("_"):
            continue
        out.append(f"| `{r['name']}` | {'yes' if r['registry'] else ''} | {r['calls']} | {', '.join(r['how'])} | {', '.join(r['test_modules'][:4])} |")
    for kind, title in (("instinct", "instinct_*"), ("tool", "tool_*")):
        out += ["", f"## Full table: {title}", "", "| function | line | registry | calls | how reached | test modules (first 4) |", "| --- | --- | --- | --- | --- | --- |"]
        for r in rows:
            if r["kind"] == kind:
                out.append(f"| `{r['name']}` | {r['line']} | {'yes' if r['registry'] else ''} | {r['calls'] or '**0**'} | {', '.join(r['how'])} | {', '.join(r['test_modules'][:4])} |")
    out += ["", "## Never called by any test", ""]
    for kind in ("instinct", "tool", "other"):
        names = [r["name"] for r in rows if r["kind"] == kind and not r["calls"] and not r["name"].startswith("_")]
        out.append(f"- **{kind}** ({len(names)}): " + (", ".join(f"`{n}`" for n in names) if names else "none"))
    out.append("")
    return "\n".join(out)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--pattern", default="test_*.py")
    parser.add_argument("--json", type=Path, default=ROOT / ".runtime" / "coverage-iat.json")
    parser.add_argument("--md", type=Path)
    args = parser.parse_args()
    sys.path.insert(0, str(ROOT / "at_the_beginning"))
    functions, recorder, result, elapsed = run(args.pattern)
    data = report(functions, recorder, result, elapsed)
    args.json.parent.mkdir(parents=True, exist_ok=True)
    args.json.write_text(json.dumps(data, indent=1), encoding="utf-8")
    text = markdown(data)
    if args.md:
        args.md.write_text(text, encoding="utf-8")
    print(text[:3000])
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(main())
