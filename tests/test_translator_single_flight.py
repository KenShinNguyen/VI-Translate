"""Concurrent workers asking for the same text must produce one engine call.

The persistent cache cannot help until the first answer is back, so the workers
on a page that repeats a string used to each open their own request for it.
"""

from __future__ import annotations

import threading
import unittest
from concurrent.futures import ThreadPoolExecutor

from pdf2zh.cache import clean_test_db, init_test_db
from pdf2zh.translator import BaseTranslator


class _CountingTranslator(BaseTranslator):
    """Records every engine call and blocks until the test releases it."""

    name = "counting"

    def __init__(self, *args, fail: bool = False, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.calls: list[str] = []
        self.entered = threading.Event()
        self.release = threading.Event()
        self.fail = fail
        self._calls_lock = threading.Lock()

    def do_translate(self, text: str) -> str:
        with self._calls_lock:
            self.calls.append(text)
        self.entered.set()
        self.release.wait(timeout=5)
        if self.fail:
            raise RuntimeError("engine refused the segment")
        return f"[{text}]"


class _WatchedInflight(dict):
    """An in-flight table that reports when callers find an entry already there.

    Timing the test on how long a worker takes to reach the gate would make it
    flaky in the direction that matters: a late worker becomes a second leader
    and opens the very second request the test is here to rule out. Watching the
    lookup itself removes the guesswork - a caller that has found the entry is
    already committed to waiting on it.
    """

    def __init__(self, expected_waiters: int) -> None:
        super().__init__()
        self.all_waiting = threading.Event()
        self._expected = expected_waiters
        self._found = 0

    def get(self, key, default=None):
        found = super().get(key, default)
        if found is not None:
            self._found += 1
            if self._found >= self._expected:
                self.all_waiting.set()
        return found


class SingleFlightTests(unittest.TestCase):
    def setUp(self) -> None:
        self.test_db = init_test_db()

    def tearDown(self) -> None:
        clean_test_db(self.test_db)

    def _translator(self, **kwargs) -> _CountingTranslator:
        return _CountingTranslator("auto", "vi", ignore_cache=True, **kwargs)

    def _run_concurrently(self, translator, text: str, workers: int):
        """Start `workers` calls, let every follower reach the gate, then answer."""
        watched = _WatchedInflight(expected_waiters=workers - 1)
        translator._inflight = watched
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = [pool.submit(translator.translate, text) for _ in range(workers)]
            self.assertTrue(
                watched.all_waiting.wait(timeout=5), "followers never reached the gate"
            )
            translator.release.set()
            return futures

    def test_the_same_text_reaches_the_engine_once(self):
        translator = self._translator()
        futures = self._run_concurrently(translator, "Bảng 1", workers=4)
        results = [future.result(timeout=5) for future in futures]

        self.assertEqual(translator.calls, ["Bảng 1"])
        self.assertEqual(results, ["[Bảng 1]"] * 4)

    def test_a_waiter_sees_the_failure_the_leader_hit(self):
        translator = self._translator(fail=True)
        futures = self._run_concurrently(translator, "boom", workers=3)
        for future in futures:
            with self.assertRaises(RuntimeError):
                future.result(timeout=5)
        self.assertEqual(translator.calls, ["boom"])

    def test_different_texts_are_not_serialised_into_one_call(self):
        translator = self._translator()
        translator.release.set()
        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(translator.translate, ["a", "b", "c"]))
        self.assertEqual(sorted(translator.calls), ["a", "b", "c"])
        self.assertEqual(results, ["[a]", "[b]", "[c]"])

    def test_a_failure_does_not_wedge_the_text_forever(self):
        # The entry has to be released, or every later attempt - including the
        # caller's own retry - would wait on a future that never settles.
        translator = self._translator(fail=True)
        translator.release.set()
        with self.assertRaises(RuntimeError):
            translator.translate("boom")
        self.assertEqual(translator._inflight, {})
        with self.assertRaises(RuntimeError):
            translator.translate("boom")
        self.assertEqual(translator.calls, ["boom", "boom"])

    def test_the_table_is_emptied_after_a_success(self):
        translator = self._translator()
        translator.release.set()
        translator.translate("done")
        self.assertEqual(translator._inflight, {})

    def test_a_cached_answer_still_short_circuits(self):
        translator = _CountingTranslator("auto", "vi")
        translator.release.set()
        self.assertEqual(translator.translate("Xin chào"), "[Xin chào]")
        self.assertEqual(translator.translate("Xin chào"), "[Xin chào]")
        self.assertEqual(translator.calls, ["Xin chào"])


if __name__ == "__main__":
    unittest.main()
