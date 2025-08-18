from __future__ import annotations

import os
from loguru import logger


def setup_logging(log_path: str) -> str:
	# Determine effective log path with fallback
	try:
		dirname = os.path.dirname(log_path) or "."
		os.makedirs(dirname, exist_ok=True)
		with open(log_path, "a", encoding="utf-8") as _:
			pass
		effective = log_path
	except Exception:
		fallback_dir = "/tmp"
		os.makedirs(fallback_dir, exist_ok=True)
		effective = os.path.join(fallback_dir, "worker.log")

	logger.remove()
	# Console
	logger.add(
		sink=lambda msg: print(msg, end=""),
		level="INFO",
		colorize=True,
		enqueue=True,
		backtrace=False,
		diagnose=False,
		format="{time:YYYY-MM-DD HH:mm:ss} | {level:<8} | {message}",
	)
	# File
	logger.add(
		effective,
		rotation="10 MB",
		retention="14 days",
		level="INFO",
		enqueue=True,
		backtrace=False,
		diagnose=False,
		format="{time:YYYY-MM-DD HH:mm:ss} | {level:<8} | {message}",
	)
	return effective