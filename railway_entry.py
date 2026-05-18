"""
Entrypoint unico para Railway.

Railway aplica el mismo start command a servicios que comparten repo. Este
router permite que el Web y el Worker usen el mismo codigo con variables
distintas.
"""
import os
import runpy


if os.getenv("RUN_WORKER_IN_WEB", "false").lower() in {"1", "true", "yes"}:
    runpy.run_path("worker.py", run_name="__main__")
else:
    runpy.run_path("main.py", run_name="__main__")
