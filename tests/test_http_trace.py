"""Check each published HTTP trace, including states between file replacements.

Endpoint equality cannot detect a transient mixed bundle. These tests inspect
actual filesystem mutations as well as frozen network responses.
"""
import csv
import hashlib
import json
import os
import selectors
import signal
import subprocess
import sys
import time
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import scripts.run_stack_experiments as stacks

ROOT = Path(__file__).resolve().parents[1]
CASES = {
    "express-weak", "express-strong", "python-fresh", "python-restored",
    "apache-fresh", "apache-restored",
}


def contains_bundle(trace, target):
    """Independent pointwise oracle over every recorded intermediate state."""
    return any(all(step["state"].get(k) == v for k, v in target.items())
               for step in trace)


def disk_state(directory):
    return {key: (directory / key).read_text() if (directory / key).exists()
            else None for key in ("a", "b")}


class HTTPTraceTests(unittest.TestCase):
    RAW = "data/raw/http-stacks"
    CSV = "data/derived/http_stacks.csv"

    @classmethod
    def setUpClass(cls):
        cls.records = {}
        for case in sorted(CASES):
            path = ROOT / cls.RAW / (case + ".json")
            cls.records[case] = json.loads(path.read_text())

    def test_saved_mutations_include_every_intermediate_state(self):
        for case, record in self.records.items():
            with self.subTest(case=case):
                observations = record["observations"]
                self.assertNotIn("complete_target_intervals", record)
                self.assertIn("illustrative_phase_intervals", record)
                self.assertTrue(record["history_evidence"])
                target = {"a": observations[0]["body"],
                          "b": observations[1]["body"]}
                self.assertEqual(record["target"], target)
                trace = record["mutation_trace"]
                self.assertTrue(trace)
                self.assertEqual([s["phase"] for s in trace],
                                 sorted(s["phase"] for s in trace))
                self.assertEqual({s["phase"] for s in trace}, {0, 1, 2})
                self.assertFalse(contains_bundle(trace, target))
                previous = {"a": None, "b": None}
                for step in trace:
                    state = step["state"]
                    self.assertEqual(set(state), {"a", "b"})
                    if step["replaced"] in ("a", "b"):
                        key = step["replaced"]
                        other = "b" if key == "a" else "a"
                        self.assertEqual(state[other], previous[other])
                        self.assertEqual(state[key], record["states"][step["phase"]][key])
                    else:
                        self.assertTrue(case.startswith("express-"))
                        self.assertEqual(state, record["states"][step["phase"]])
                        self.assertEqual(set(step["readback"]), {"a", "b"})
                        for key, response in step["readback"].items():
                            self.assertEqual(response["request_method"], "GET")
                            header_names = {name.lower() for name in response["request_headers"]}
                            self.assertFalse(header_names & {"if-none-match", "if-modified-since"})
                            self.assertEqual(response["status"], 200)
                            self.assertEqual(response["body"], state[key])
                            self.assertEqual(response["body_sha256"], hashlib.sha256(
                                state[key].encode()).hexdigest())
                    previous = state
                for phase in range(3):
                    steps = [s for s in trace if s["phase"] == phase]
                    self.assertEqual(steps[-1]["state"], record["states"][phase])
                    self.assertEqual(len(steps), 1 if case.startswith("express-") else 2)
                if not case.startswith("express-"):
                    restore = [s for s in trace if s["phase"] == 2]
                    self.assertEqual(restore[0]["state"], {
                        "a": record["states"][1]["a"],
                        "b": record["states"][2]["b"],
                    })
                self.assertEqual(record["target_bundle_ever_present"],
                                 contains_bundle(trace, target))

    def test_endpoint_and_conditional_claims_follow_from_responses(self):
        accepted = 0
        for case, record in self.records.items():
            with self.subTest(case=case):
                obs = record["observations"]
                self.assertEqual(len(obs), 5)
                self.assertEqual([(o["resource"], o["tick"]) for o in obs],
                                 [("a", 0), ("b", 1), ("b", 2), ("a", 3), ("a", 3)])
                a0, b1, b2, a3, conditional = obs
                for entry in obs:
                    self.assertEqual(entry["body_sha256"], hashlib.sha256(
                        entry["body"].encode()).hexdigest())
                    self.assertEqual(entry["request_method"], "GET")
                    self.assertIsInstance(entry["request_headers"], dict)
                self.assertEqual([o["status"] for o in obs[:4]], [200] * 4)
                self.assertTrue(all(o["body"] for o in obs[:4]))
                for entry in obs[:4]:
                    names = {key.lower() for key in entry["request_headers"]}
                    self.assertFalse(names & {"if-none-match", "if-modified-since"})
                self.assertEqual(a0["body"], a3["body"])
                self.assertEqual(b1["body"], b2["body"])
                self.assertEqual(a0["body"], record["states"][0]["a"])
                self.assertEqual(b1["body"], record["states"][1]["b"])
                validator = "etag" if a0["etag"] is not None else "last_modified"
                self.assertEqual(record["validator"], validator)
                self.assertTrue(all(o[validator] for o in obs[:4]))
                if case == "express-weak":
                    self.assertTrue(all(o["etag"].startswith('W/"') for o in obs[:4]))
                if case == "express-strong":
                    self.assertTrue(all(o["etag"].startswith('"') for o in obs[:4]))
                endpoint_equal = a0[validator] == a3[validator]
                would_accept = endpoint_equal and b1[validator] == b2[validator]
                self.assertEqual(record["endpoint_validator_equal"], endpoint_equal)
                self.assertEqual(record["consumer_endpoint_rule_would_accept"], would_accept)
                self.assertEqual(record["conditional_status"], conditional["status"])
                self.assertEqual(conditional["status"], 304 if endpoint_equal else 200)
                self.assertEqual(conditional["body"], "" if endpoint_equal else a3["body"])
                headers = {k.lower(): v for k, v in conditional["request_headers"].items()}
                name = "if-none-match" if validator == "etag" else "if-modified-since"
                conditionals = {key: value for key, value in headers.items()
                                if key in {"if-none-match", "if-modified-since"}}
                self.assertEqual(conditionals, {name: a0[validator]})
                accepted += would_accept
        self.assertEqual(accepted, 4)

    def test_published_csv_is_derived_from_raw_observations(self):
        with (ROOT / self.CSV).open(newline="") as stream:
            rows = list(csv.DictReader(stream))
        self.assertEqual({row["case"] for row in rows}, CASES)
        self.assertEqual(len(rows), len(CASES))
        for row in rows:
            record = self.records[row["case"]]
            a0, b1, b2, a3, conditional = record["observations"]
            key = "etag" if a0["etag"] is not None else "last_modified"
            expected = {
                "validator": key,
                "endpoint_validator_equal": str(a0[key] == a3[key]),
                "conditional_status": str(conditional["status"]),
                "consumer_endpoint_rule_would_accept": str(
                    a0[key] == a3[key] and b1[key] == b2[key]),
                "target_bundle_ever_present": str(contains_bundle(
                    record["mutation_trace"], {"a": a0["body"], "b": b1["body"]})),
            }
            for key, value in expected.items():
                self.assertEqual(row[key], value, (row["case"], key))

    def test_static_files_observes_real_atomic_replacement_states(self):
        for preserve in (False, True):
            with self.subTest(preserve_mtime=preserve), tempfile.TemporaryDirectory() as temporary:
                directory = Path(temporary)
                observed, recorded = [], []
                original_replace = os.replace

                def replace_and_observe(source, destination):
                    original_replace(source, destination)
                    observed.append(disk_state(directory))

                with patch.object(stacks.os, "replace", side_effect=replace_and_observe):
                    for phase in range(3):
                        recorded.extend(stacks.static_files(directory, phase, preserve))
                        self.assertEqual(disk_state(directory), stacks.STATES[phase])
                self.assertEqual([step["state"] for step in recorded], observed)
                self.assertEqual(len(observed), 6)
                target = {"a": stacks.STATES[0]["a"], "b": stacks.STATES[1]["b"]}
                self.assertFalse(contains_bundle(recorded, target))
                self.assertEqual(observed[4], {
                    "a": stacks.STATES[1]["a"], "b": stacks.STATES[2]["b"]})
                self.assertEqual(observed[5], stacks.STATES[2])
                expected_stamp = 1600000000 if preserve else 1600000020
                self.assertEqual((directory / "a").stat().st_mtime, expected_stamp)
                self.assertEqual((directory / "b").stat().st_mtime, expected_stamp)

    def test_old_a_then_b_restoration_has_detectable_mixed_state(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            stacks.static_files(directory, 0, False)
            stacks.static_files(directory, 1, False)
            trace = [{"state": disk_state(directory)}]
            # Replay the previous faulty order independently of static_files.
            for key in ("a", "b"):
                pending = directory / (key + ".pending")
                pending.write_text(stacks.STATES[2][key])
                os.replace(pending, directory / key)
                trace.append({"state": disk_state(directory)})
            target = {"a": stacks.STATES[0]["a"], "b": stacks.STATES[1]["b"]}
            self.assertNotEqual(trace[0]["state"], target)
            self.assertEqual(trace[1]["state"], target)
            self.assertNotEqual(trace[-1]["state"], target)
            self.assertTrue(contains_bundle(trace, target))
            self.assertFalse(contains_bundle([trace[0], trace[-1]], target))

    def test_client_performs_get_with_conditional_header_and_reads_body(self):
        class Response:
            status = 200
            headers = {"ETag": '"e1"', "Content-Type": "text/plain"}

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def read(self):
                return b"representation bytes\n"

        with patch.object(stacks, "urlopen", return_value=Response()) as open_url:
            result = stacks.request(12345, "a", {"If-None-Match": '"e0"'})
        sent = open_url.call_args.args[0]
        self.assertEqual(sent.get_method(), "GET")
        self.assertEqual(sent.full_url, "http://127.0.0.1:12345/a")
        self.assertEqual({k.lower(): v for k, v in sent.header_items()},
                         {"if-none-match": '"e0"'})
        self.assertEqual(result["body"], "representation bytes\n")
        self.assertEqual(result["etag"], '"e1"')


@unittest.skipUnless(os.name == "posix", "HTTP server sessions use POSIX process groups")
class HTTPServerLifecycleTests(unittest.TestCase):
    def test_partial_startup_line_has_a_deadline(self):
        proc = subprocess.Popen(
            [sys.executable, "-c", "import os,time; os.write(1,b'{partial'); time.sleep(30)"],
            stdout=subprocess.PIPE, start_new_session=True)
        try:
            started = time.monotonic()
            with self.assertRaises(TimeoutError):
                stacks.read_startup_metadata(proc, timeout=.1)
            self.assertLess(time.monotonic() - started, 2)
        finally:
            try:
                stacks.stop_owned_session(proc, timeout=.2)
            finally:
                proc.stdout.close()
        self.assertIsNotNone(proc.returncode)

    def test_exit_between_poll_and_probe_is_reaped_before_retry(self):
        proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"],
                                start_new_session=True)
        real_killpg = os.killpg
        injected = False

        def exit_race(group, sig):
            nonlocal injected
            self.assertEqual(group, proc.pid)
            if sig == 0 and not injected:
                # The preceding TERM has been delivered. Force the leader's
                # exit between the earlier poll and this group-existence test.
                proc.wait(timeout=2)
                injected = True
                raise PermissionError(1, "zombie-only group probe")
            return real_killpg(group, sig)

        try:
            with patch.object(stacks.os, "killpg", side_effect=exit_race):
                stacks.stop_owned_session(proc, timeout=.2)
            self.assertTrue(injected)
            self.assertEqual(proc.returncode, -signal.SIGTERM)
        finally:
            if proc.poll() is None:
                proc.kill()
            proc.wait(timeout=2)

    def test_permission_denial_for_a_live_group_is_not_suppressed(self):
        proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"],
                                start_new_session=True)
        try:
            with patch.object(stacks.os, "killpg", side_effect=PermissionError(1, "denied")):
                with self.assertRaises(PermissionError):
                    stacks.stop_owned_session(proc, timeout=.1)
            self.assertIsNone(proc.poll())
        finally:
            proc.kill()
            proc.wait(timeout=2)

    def test_group_inspection_distinguishes_zombies_and_fails_closed(self):
        for text, expected in (("101 99 Z\n102 88 S\n", False),
                               ("101 99 Z\n103 99 S+\n", True), ("102 88 S\n", False)):
            result = subprocess.CompletedProcess([], 0, stdout=text, stderr="")
            with self.subTest(text=text), patch.object(stacks.subprocess, "run", return_value=result):
                self.assertEqual(stacks._group_has_live_members(99), expected)
        for text in ("partial row\n", ""):
            bad = subprocess.CompletedProcess([], 0, stdout=text, stderr="")
            with patch.object(stacks.subprocess, "run", return_value=bad):
                with self.assertRaises(RuntimeError):
                    stacks._group_has_live_members(99)
        with patch.object(stacks.subprocess, "run", side_effect=subprocess.CalledProcessError(1, "ps")):
            with self.assertRaises(subprocess.CalledProcessError):
                stacks._group_has_live_members(99)

    def test_worker_is_stopped_after_its_leader_has_exited(self):
        worker = ("import os,signal,time,json; signal.signal(signal.SIGTERM,signal.SIG_IGN); "
                  "print(json.dumps({'port':1,'worker':os.getpid()}),flush=True); time.sleep(30)")
        leader = ("import subprocess,sys,time; subprocess.Popen([sys.executable,'-c',"
                  + repr(worker) + "]); time.sleep(30)")
        proc = subprocess.Popen([sys.executable, "-c", leader],
                                stdout=subprocess.PIPE, start_new_session=True)
        try:
            meta = stacks.read_startup_metadata(proc, timeout=2)
            self.assertEqual(os.getpgid(meta["worker"]), proc.pid)
            # Kill only the leader first, leaving the confirmed worker alive.
            proc.terminate()
            proc.wait(timeout=2)
            self.assertEqual(proc.returncode, -signal.SIGTERM)
            self.assertEqual(os.getpgid(meta["worker"]), proc.pid)
            stacks.stop_owned_session(proc, timeout=.1)
            with selectors.DefaultSelector() as ready:
                ready.register(proc.stdout, selectors.EVENT_READ)
                self.assertTrue(ready.select(2), "orphan worker retained the pipe")
                self.assertEqual(os.read(proc.stdout.fileno(), 1), b"")
        finally:
            try:
                stacks.stop_owned_session(proc, timeout=.1)
            finally:
                proc.stdout.close()

    def test_popen_failure_closes_the_log(self):
        logs = []

        def fail_launch(*args, **kwargs):
            logs.append(kwargs["stderr"])
            raise OSError("synthetic launch failure")

        with tempfile.TemporaryDirectory() as temporary:
            with patch.object(stacks, "ROOT", Path(temporary)), \
                 patch.object(stacks.subprocess, "Popen", side_effect=fail_launch):
                with self.assertRaisesRegex(OSError, "synthetic launch failure"):
                    stacks.run_one("test-weak", "express")
        self.assertEqual(len(logs), 1)
        self.assertTrue(logs[0].closed)

    def test_startup_parse_and_readiness_failures_reap_and_close(self):
        real_popen = subprocess.Popen
        real_killpg = os.killpg
        server_command = ["node", "express_server.cjs", "weak"]
        inspection_command = ["/bin/ps", "-axo", "pid=,pgid=,stat="]
        for failure in ("bad-json", "readiness"):
            for force_inspection in (False, True):
                launched, logs, delegated = [], [], []
                denied_probes = 0
                text = "{invalid" if failure == "bad-json" else '{"port":12345}'
                code = "import time; print(" + repr(text) + ",flush=True); time.sleep(30)"

                def launch_test_child(*args, **kwargs):
                    # subprocess.run uses this same module's Popen for ps.
                    # Replace only the server, preserving real helper commands.
                    if not args or args[0] != server_command:
                        delegated.append(args[0] if args else kwargs.get("args"))
                        return real_popen(*args, **kwargs)
                    logs.append(kwargs["stderr"])
                    proc = real_popen([sys.executable, "-c", code],
                                     stdout=kwargs["stdout"], stderr=kwargs["stderr"],
                                     start_new_session=kwargs["start_new_session"])
                    launched.append(proc)
                    return proc

                def probe_exited_group(group, sig):
                    nonlocal denied_probes
                    self.assertEqual(group, launched[0].pid)
                    if force_inspection and sig == 0 and denied_probes < 2:
                        # TERM was really delivered. Reap the leader, then
                        # force both EPERM probes so real ps must run while
                        # Popen is patched, regardless of OS race timing.
                        launched[0].wait(timeout=2)
                        denied_probes += 1
                        raise PermissionError(1, "synthetic exited-group probe")
                    return real_killpg(group, sig)

                with self.subTest(failure=failure, force_inspection=force_inspection), \
                     tempfile.TemporaryDirectory() as temporary:
                    try:
                        with patch.object(stacks, "ROOT", Path(temporary)), \
                             patch.object(stacks.subprocess, "Popen", side_effect=launch_test_child), \
                             patch.object(stacks.os, "killpg", side_effect=probe_exited_group), \
                             patch.object(stacks, "wait_ready", side_effect=TimeoutError("synthetic readiness failure")):
                            error = json.JSONDecodeError if failure == "bad-json" else TimeoutError
                            with self.assertRaises(error):
                                stacks.run_one("test-weak", "express")
                        self.assertEqual(len(launched), 1)
                        self.assertIsNotNone(launched[0].returncode)
                        self.assertTrue(launched[0].stdout.closed)
                        self.assertTrue(logs[0].closed)
                        if force_inspection:
                            self.assertEqual(denied_probes, 2)
                            self.assertIn(inspection_command, delegated)
                    finally:
                        # A failing assertion/mock must not leak our fixture.
                        # Verify production cleanup above before this safety net.
                        for proc in launched:
                            if proc.poll() is None:
                                proc.kill()
                            proc.wait(timeout=2)
                            if proc.stdout is not None:
                                proc.stdout.close()

    def test_cleanup_escalates_only_the_owned_group_and_stops_its_worker(self):
        code = ("import signal,subprocess,sys,time,json; "
                "signal.signal(signal.SIGTERM,signal.SIG_IGN); "
                "worker=subprocess.Popen([sys.executable,'-c','import time; time.sleep(30)']); "
                "print(json.dumps({'port':1,'worker':worker.pid}),flush=True); time.sleep(30)")
        proc = subprocess.Popen([sys.executable, "-c", code],
                                stdout=subprocess.PIPE, start_new_session=True)
        signals = []
        original_killpg = os.killpg

        def signal_owned(group, sig):
            self.assertEqual(group, proc.pid)
            self.assertNotEqual(group, os.getpgrp())
            signals.append(sig)
            return original_killpg(group, sig)

        try:
            meta = stacks.read_startup_metadata(proc, timeout=2)
            self.assertEqual(os.getpgid(meta["worker"]), proc.pid)
            with patch.object(stacks.os, "killpg", side_effect=signal_owned):
                stacks.stop_owned_session(proc, timeout=.1)
            self.assertIn(signal.SIGTERM, signals)
            self.assertIn(signal.SIGKILL, signals)
            self.assertEqual(proc.returncode, -signal.SIGKILL)
            # Both processes hold the pipe; EOF verifies the worker also stopped.
            with selectors.DefaultSelector() as ready:
                ready.register(proc.stdout, selectors.EVENT_READ)
                self.assertTrue(ready.select(2), "worker retained the stdout pipe")
                self.assertEqual(os.read(proc.stdout.fileno(), 1), b"")
        finally:
            try:
                stacks.stop_owned_session(proc, timeout=.1)
            finally:
                proc.stdout.close()




class LinuxHTTPTraceTests(unittest.TestCase):
    """The same trace checks on the Linux replication (Apache 2.4.58, Python 3.13)."""
    RAW = "data/raw/http-stacks-linux"
    CSV = "data/derived/http_stacks_linux.csv"
    setUpClass = classmethod(HTTPTraceTests.setUpClass.__func__)
    test_saved_mutations_include_every_intermediate_state = \
        HTTPTraceTests.test_saved_mutations_include_every_intermediate_state
    test_endpoint_and_conditional_claims_follow_from_responses = \
        HTTPTraceTests.test_endpoint_and_conditional_claims_follow_from_responses
    test_published_csv_is_derived_from_raw_observations = \
        HTTPTraceTests.test_published_csv_is_derived_from_raw_observations

    def test_replication_matches_the_frozen_macos_outcomes(self):
        macos = {case: json.loads((ROOT / HTTPTraceTests.RAW / (case + ".json")).read_text()) for case in CASES}
        for case, record in self.records.items():
            with self.subTest(case=case):
                self.assertEqual(record["platform"]["system"], "Linux")
                for key in ("validator", "endpoint_validator_equal", "conditional_status",
                            "target_bundle_ever_present", "consumer_endpoint_rule_would_accept"):
                    self.assertEqual(record[key], macos[case][key])


if __name__ == "__main__":
    unittest.main()
