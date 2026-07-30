"""Application shutdown coordination for Project Aurora."""

import traceback


class ShutdownManager:
    """Collect application cleanup callbacks and Tk after timers."""

    def __init__(self, logger=None):
        self.logger = logger
        self.cleanup_callbacks = []
        self.after_ids = set()
        self.shutting_down = False

    def register_cleanup(self, callback, name="cleanup"):
        if callable(callback):
            self.cleanup_callbacks.append((name, callback))
        return callback

    def register_after(self, after_id):
        if after_id:
            self.after_ids.add(after_id)
        return after_id

    def forget_after(self, after_id):
        self.after_ids.discard(after_id)

    def cancel_after_timers(self, root):
        for after_id in list(self.after_ids):
            try:
                root.after_cancel(after_id)
            except Exception:
                pass
            finally:
                self.after_ids.discard(after_id)

    def shutdown(self):
        if self.shutting_down:
            return False
        self.shutting_down = True
        if self.logger is not None:
            try:
                self.logger.info("ShutdownManager.shutdown() started")
            except Exception:
                pass
        for name, callback in reversed(self.cleanup_callbacks):
            try:
                if self.logger is not None:
                    self.logger.info(f"Shutdown cleanup started: {name}")
                callback()
                if self.logger is not None:
                    self.logger.info(f"Shutdown cleanup finished: {name}")
            except Exception as error:
                if self.logger is not None:
                    try:
                        self.logger.error(f"Shutdown cleanup failed: {name}: {error}")
                        self.logger.error(traceback.format_exc())
                    except Exception:
                        pass
        return True
