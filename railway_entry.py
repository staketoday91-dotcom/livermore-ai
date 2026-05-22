"""
Entrypoint unico para Railway.

Livermore oficial en cloud: un solo servicio web (main.py) con Discord+scanner.
Servicio worker separado solo si LIVERMORE_SERVICE=worker (legacy).
"""
import os
import runpy

service = os.getenv("LIVERMORE_SERVICE", "web").strip().lower()

# Un solo servicio web recomendado (Discord+scanner via should_run_worker_in_web).
if service == "worker":
    runpy.run_path("worker.py", run_name="__main__")
else:
    runpy.run_path("main.py", run_name="__main__")
