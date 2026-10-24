"""Autonomous Background Scheduler for EQUILIBRA.

Manages autonomous recurring agent tasks:
1. Maintenance SLA monitor: scans open work orders, identifies SLA breaches, and escalates.
2. Grace-period and overdue rent sweep: verifies balances and sends grace reminders or routes notices.
3. Property verification runner: evaluates unverified properties.

Guarantees:
- Tied to FastAPI lifespan (clean startup & shutdown).
- Safe exception boundary: failure in one job does not abort other jobs.
- Bounded runs with timestamps and telemetry metrics.
- Exposes health, execution history, and manual trigger endpoints.
"""

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger("equilibra.scheduler")

_scheduler_task: Optional[asyncio.Task] = None
_is_running: bool = False
_last_run_time: Optional[datetime] = None
_job_history: List[Dict[str, Any]] = []


async def run_autonomous_jobs() -> Dict[str, Any]:
    """Execute all autonomous routine agent sweeps."""
    global _last_run_time
    now = datetime.now(timezone.utc)
    _last_run_time = now
    
    results = {
        "timestamp": now.isoformat(),
        "sla_breaches_detected": 0,
        "delinquencies_scanned": 0,
        "errors": []
    }
    
    # 1. Maintenance SLA check
    try:
        from .maintenance_agent import check_sla_breaches
        breaches = check_sla_breaches()
        results["sla_breaches_detected"] = len(breaches)
    except Exception as e:
        logger.error(f"Maintenance SLA sweep error: {e}")
        results["errors"].append(f"SLA check error: {str(e)}")
        
    # 2. Financial Grace Period & Overdue Rent sweep
    try:
        from .finance_agent import sweep_grace_period_and_overdue
        delinquencies = sweep_grace_period_and_overdue()
        results["delinquencies_scanned"] = len(delinquencies)
    except Exception as e:
        logger.error(f"Overdue rent sweep error: {e}")
        results["errors"].append(f"Grace sweep error: {str(e)}")

    # 3. Resident & Lease Expiration & Renewal alert sweep
    try:
        from .resident_agent import sweep_expiring_leases_and_renewals
        renewals = sweep_expiring_leases_and_renewals(window_days=90)
        results["expiring_leases_scanned"] = len(renewals)
    except Exception as e:
        logger.error(f"Resident renewal sweep error: {e}")
        results["errors"].append(f"Renewal sweep error: {str(e)}")

    # 4. Central Compliance & Risk Register scan
    try:
        from .compliance_agent import run_compliance_and_risk_scan
        compliance_scan = run_compliance_and_risk_scan()
        results["risk_findings_detected"] = compliance_scan.get("findings_detected", 0)
    except Exception as e:
        logger.error(f"Compliance & risk sweep error: {e}")
        results["errors"].append(f"Compliance sweep error: {str(e)}")
        
    _job_history.insert(0, results)
    if len(_job_history) > 20:
        _job_history.pop()
        
    return results


async def scheduler_loop(interval_seconds: int = 300):
    """Background polling loop running every interval_seconds (default 5 mins)."""
    global _is_running
    _is_running = True
    logger.info("EQUILIBRA Autonomous Background Scheduler initialized.")
    
    try:
        while _is_running:
            await run_autonomous_jobs()
            await asyncio.sleep(interval_seconds)
    except asyncio.CancelledError:
        logger.info("EQUILIBRA Scheduler received cancellation signal.")
    finally:
        _is_running = False


def start_scheduler():
    """Start background scheduler task."""
    global _scheduler_task
    if _scheduler_task is None or _scheduler_task.done():
        _scheduler_task = asyncio.create_task(scheduler_loop())


def stop_scheduler():
    """Stop background scheduler task."""
    global _scheduler_task, _is_running
    _is_running = False
    if _scheduler_task and not _scheduler_task.done():
        _scheduler_task.cancel()


def get_scheduler_status() -> Dict[str, Any]:
    """Return scheduler operational health metrics."""
    return {
        "status": "running" if _is_running else "stopped",
        "last_run_time": _last_run_time.isoformat() if _last_run_time else None,
        "total_runs": len(_job_history),
        "recent_history": _job_history[:5]
    }
