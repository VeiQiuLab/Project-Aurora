import threading
import unittest

from widgets.pages.chat_page import ChatPage


class Logger:
    def __init__(self):
        self.messages = []

    def info(self, message):
        self.messages.append(str(message))


def make_gate():
    page = ChatPage.__new__(ChatPage)
    page._turn_lock = threading.Lock()
    page._turn_counter = 0
    page.logger = Logger()
    return page


class ChatTurnGateTests(unittest.TestCase):
    def test_only_one_active_turn(self):
        page = make_gate()

        self.assertTrue(page._try_begin_turn("text"))
        self.assertFalse(page._try_begin_turn("voice"))
        page._end_turn("text")
        self.assertTrue(page._try_begin_turn("voice"))
        page._end_turn("voice")

    def test_busy_attempt_does_not_wait_or_change_owner(self):
        page = make_gate()
        self.assertTrue(page._try_begin_turn("voice"))
        self.assertFalse(page._try_begin_turn("text"))
        self.assertEqual(page._turn_counter, 1)
        page._end_turn("voice")

    def test_release_is_idempotent_after_exception_cleanup(self):
        page = make_gate()
        self.assertTrue(page._try_begin_turn("voice"))
        page._end_turn("voice")
        page._end_turn("voice")
        self.assertTrue(page._try_begin_turn("text"))
        page._end_turn("text")


if __name__ == "__main__":
    unittest.main()
