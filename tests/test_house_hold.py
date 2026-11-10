"""Timing rules for the spoken hold line. No Discord, no network."""

import asyncio
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'assistant'))
os.environ["HOUSE_HOLD_SECONDS"] = "0.2"
os.environ["HOUSE_HOLD_PAD_SECONDS"] = "0.05"

import house_hold  # noqa: E402


class HoldTests(unittest.TestCase):
    def test_fast_reply_never_speaks(self):
        calls = []

        async def speak(phrase, cancel):
            calls.append(phrase)
            return True

        async def run():
            hold = house_hold.HouseHold(speak, delay=0.2, pad=0.05)
            hold.start()
            await asyncio.sleep(0.05)
            await hold.finish(speak_answer=True)
            return hold.spoke

        self.assertFalse(asyncio.run(run()))
        self.assertEqual(calls, [])

    def test_slow_reply_speaks_once_then_pads(self):
        calls = []

        async def speak(phrase, cancel):
            await asyncio.sleep(0.05)
            if cancel.is_set():
                return False
            calls.append(phrase)
            await asyncio.sleep(0.15)
            return True

        async def run():
            hold = house_hold.HouseHold(speak, delay=0.05, pad=0.05)
            hold.start()
            await asyncio.sleep(0.2)
            await hold.finish(speak_answer=True)
            return hold.spoke

        self.assertTrue(asyncio.run(run()))
        self.assertEqual(len(calls), 1)
        self.assertIn(calls[0], house_hold.FIRST_LINES)

    def test_still_waiting_adds_the_wait_line(self):
        calls = []

        async def speak(phrase, cancel):
            calls.append(phrase)
            return True

        async def run():
            hold = house_hold.HouseHold(speak, delay=0.05, pad=0)
            hold.start()
            await asyncio.sleep(0.25)
            self.assertEqual(len(calls), 2)
            await hold.finish(speak_answer=False)

        asyncio.run(run())
        self.assertEqual(calls[1], house_hold.WAIT_LINE)

    def test_cancel_during_synthesis_does_not_count(self):
        calls = []

        async def speak(phrase, cancel):
            await asyncio.sleep(0.1)
            if cancel.is_set():
                return False
            calls.append(phrase)
            return True

        async def run():
            hold = house_hold.HouseHold(speak, delay=0.05, pad=0.05)
            hold.start()
            await asyncio.sleep(0.08)
            await hold.finish(speak_answer=True)
            return hold.spoke

        self.assertFalse(asyncio.run(run()))
        self.assertEqual(calls, [])


if __name__ == "__main__":
    unittest.main()
