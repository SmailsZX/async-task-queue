"""Taskiq worker runner — запуск воркера через Taskiq CLI."""

from taskiq.cli.worker.args import WorkerArgs
from taskiq.cli.worker.run import run_worker


def main() -> None:
    """Запускает воркер Taskiq через CLI."""
    args = WorkerArgs(
        broker="app.tasks.worker:broker",
        modules=["app.tasks"],
        fs_discover=True,
        workers=1,
        log_level="INFO",
    )
    run_worker(args)


if __name__ == "__main__":
    main()
