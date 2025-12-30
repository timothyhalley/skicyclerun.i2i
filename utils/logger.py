import logging

# Global flag for verbose output (set by pipeline.py)
VERBOSE = False

def logInfo(message):
    # Only use logging - handler will print to console
    logging.info(message)

def logError(message):
    logging.error(message)

def logWarn(message):
    logging.warning(message)

def logDebug(message):
    logging.debug(message)

def logProgress(message):
    """Always show progress messages even without --verbose"""
    logging.info(message)