from __future__ import annotations

import logging
from datetime import datetime

from antigravity.db import AgentRun, session_scope

logger = logging.getLogger("antigravity.agent")


class BaseAgent:
    name = "base"

    def execute(self) -> int:
        raise NotImplementedError

    def run_once(self) -> int:
        started_at = datetime.utcnow()
        run_id = None
        try:
            with session_scope() as session:
                run = AgentRun(agent_name=self.name, status="RUNNING", started_at=started_at)
                session.add(run)
                session.flush()
                run_id = run.id

            processed = self.execute()

            with session_scope() as session:
                run = session.get(AgentRun, run_id)
                if run:
                    run.status = "SUCCESS"
                    run.finished_at = datetime.utcnow()
                    run.records_processed = processed
                    run.message = f"{processed} records processed"
            return processed
        except Exception as exc:
            logger.exception("%s failed", self.name)
            with session_scope() as session:
                run = session.get(AgentRun, run_id) if run_id else None
                if run:
                    run.status = "ERROR"
                    run.finished_at = datetime.utcnow()
                    run.error = str(exc)
            return 0

