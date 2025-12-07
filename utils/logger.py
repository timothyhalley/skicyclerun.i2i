import logging

# Global flag for verbose output (set by pipeline.py)
VERBOSE = False

def logInfo(message):
    if VERBOSE:
        print(message)
    logging.info(message)

def logError(message):
    print(f"❌ {message}")  # Always show errors
    logging.error(message)

def logWarn(message):
    print(f"⚠️ {message}")  # Always show warnings
    logging.warning(message)

def logDebug(message):
    if logging.getLogger().isEnabledFor(logging.DEBUG):
        print(f"[DEBUG] {message}")
    logging.debug(message)

def logProgress(message):
    """Always show progress messages even without --verbose"""
    print(message)
    logging.info(message)