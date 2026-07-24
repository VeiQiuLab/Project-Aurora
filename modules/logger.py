from pathlib import Path
from datetime import datetime
from collections import deque
import logging


class AuroraLogger:
    def __init__(self):
        self.base_dir = Path(__file__).resolve().parent.parent
        self.log_dir = self.base_dir / "logs"
        self.log_dir.mkdir(parents=True, exist_ok=True)

        self.log_file = self.log_dir / "aurora.log"

        self.logger = logging.getLogger("ProjectAurora")

        # 最近日志（内存）
        self.recent_logs = deque(maxlen=20)

        if not self.logger.handlers:
            self.logger.setLevel(logging.INFO)

            formatter = logging.Formatter(
                "[%(asctime)s] [%(levelname)s] %(message)s",
                "%Y-%m-%d %H:%M:%S"
            )

            file_handler = logging.FileHandler(
                self.log_file,
                encoding="utf-8"
            )
            file_handler.setFormatter(formatter)

            console_handler = logging.StreamHandler()
            console_handler.setFormatter(formatter)

            self.logger.addHandler(file_handler)
            self.logger.addHandler(console_handler)

    def _append_recent(self, message: str):
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.recent_logs.append(f"{timestamp}  {message}")

    def get_recent_logs(self):
        return list(self.recent_logs)

    def get_recent_logs_text(self):
        return "\n".join(self.get_recent_logs())

    def clear_recent_logs(self):
        self.recent_logs.clear()

    def info(self, message: str):
        self.logger.info(message)
        self._append_recent(message)

    def warning(self, message: str):
        self.logger.warning(message)
        self._append_recent(message)

    def error(self, message: str):
        self.logger.error(message)
        self._append_recent(message)

    def debug(self, message: str):
        self.logger.debug(message)
        self._append_recent(message)

    def exception(self, message: str):
        self.logger.exception(message)
        self._append_recent(message)

    def separator(self):
        self.logger.info("-" * 60)

    def startup(self):
        self.separator()
        self.info("Project Aurora · Xu")
        self.info(
            f"Startup Time : {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        )
        self.separator()


logger = AuroraLogger()
