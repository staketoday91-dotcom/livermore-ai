from __future__ import annotations

import argparse
import logging
import time

from apscheduler.schedulers.background import BackgroundScheduler

from antigravity.agents.backtest import ContractBacktestAgent
from antigravity.agents.flow import WhaleScannerAgent
from antigravity.agents.macro import MacroAgent
from antigravity.agents.microstructure import MicrostructureAgent
from antigravity.agents.monitor import ContractMonitorAgent
from antigravity.agents.portfolio import PortfolioCommitteeAgent
from antigravity.agents.sector import SectorAgent
from antigravity.agents.tide import MarketTideAgent
from antigravity.config import get_settings
from antigravity.db import init_db


def build_agents():
    return {
        "macro": MacroAgent(),
        "sector": SectorAgent(),
        "tide": MarketTideAgent(),
        "flow": WhaleScannerAgent(),
        "monitor": ContractMonitorAgent(),
        "microstructure": MicrostructureAgent(),
        "portfolio": PortfolioCommitteeAgent(),
        "backtest": ContractBacktestAgent(),
    }


def run_once(agent_name: str | None = None) -> None:
    init_db()
    agents = build_agents()
    selected = [agents[agent_name]] if agent_name else agents.values()
    for agent in selected:
        processed = agent.run_once()
        logging.info("%s processed %s records", agent.name, processed)


def run_forever() -> None:
    settings = get_settings()
    init_db()
    agents = build_agents()

    scheduler = BackgroundScheduler(timezone="America/New_York")
    scheduler.add_job(agents["macro"].run_once, "interval", seconds=settings.macro_interval_seconds, id="macro", replace_existing=True, max_instances=1)
    scheduler.add_job(agents["sector"].run_once, "interval", seconds=settings.sector_interval_seconds, id="sector", replace_existing=True, max_instances=1)
    scheduler.add_job(agents["tide"].run_once, "interval", seconds=settings.agent_loop_interval_seconds, id="tide", replace_existing=True, max_instances=1)
    scheduler.add_job(agents["flow"].run_once, "interval", seconds=settings.whale_interval_seconds, id="flow", replace_existing=True, max_instances=1)
    scheduler.add_job(agents["monitor"].run_once, "interval", seconds=settings.whale_interval_seconds, id="monitor", replace_existing=True, max_instances=1)
    scheduler.add_job(agents["microstructure"].run_once, "interval", seconds=settings.agent_loop_interval_seconds, id="microstructure", replace_existing=True, max_instances=1)
    scheduler.add_job(agents["portfolio"].run_once, "interval", seconds=settings.agent_loop_interval_seconds, id="portfolio", replace_existing=True, max_instances=1)
    scheduler.add_job(agents["backtest"].run_once, "interval", seconds=settings.agent_loop_interval_seconds, id="backtest", replace_existing=True, max_instances=1)

    scheduler.start()
    logging.info("Antigravity worker started")

    run_once()
    try:
        while True:
            time.sleep(60)
    except KeyboardInterrupt:
        scheduler.shutdown(wait=False)


def main() -> None:
    settings = get_settings()
    logging.basicConfig(level=settings.log_level, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    parser = argparse.ArgumentParser(description="Antigravity agentic worker")
    parser.add_argument("--once", action="store_true", help="Run agents once and exit")
    parser.add_argument("--agent", choices=list(build_agents().keys()), help="Run only one agent")
    args = parser.parse_args()

    if args.once or args.agent:
        run_once(args.agent)
    else:
        run_forever()


if __name__ == "__main__":
    main()

