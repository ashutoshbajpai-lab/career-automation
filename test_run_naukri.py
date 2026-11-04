"""
test_run_naukri.py - Runs the live Naukri automation to search, apply, and route jobs.
"""

import logging
from naukri_automator import NaukriAutomator

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("NaukriRun")

def main():
    logger.info("=" * 65)
    logger.info("       STARTING LIVE NAUKRI APPLY AUTOMATION RUN          ")
    logger.info("=" * 65)

    naukri = NaukriAutomator()

    # Step 1: Execute Daily Profile Boost first
    logger.info("Step 1: Running Daily Recency Algorithm Boost...")
    boost_res = naukri.boost_profile()
    logger.info(f"Boost Result: {boost_res}")

    # Step 2: Apply to live Analyst & APM openings
    logger.info("\nStep 2: Starting High-Volume Auto-Apply pipeline...")
    target_roles = ["Analyst", "Product Manager", "Data Analyst"]
    res = naukri.apply_jobs(target_roles=target_roles, daily_target=10)

    logger.info("\n" + "=" * 65)
    logger.info("              NAUKRI RUN SUMMARY RESULTS                 ")
    logger.info("=" * 65)
    logger.info(f"Direct Applied Count: {res.get('applied_count')}")
    logger.info(f"MNC / Manual Queued:  {res.get('manual_queued_count')}")
    
    if res.get('applied_jobs'):
        logger.info("\nApplied Postings:")
        for a in res['applied_jobs']:
            logger.info(f"  • {a['title']} at {a['company']} ({a['location']})")

    if res.get('manual_jobs'):
        logger.info("\nRouted to Manual Desk (MNC/Workday):")
        for m in res['manual_jobs']:
            logger.info(f"  • {m['title']} at {m['company']} -> {m['reason']}")

if __name__ == "__main__":
    main()
