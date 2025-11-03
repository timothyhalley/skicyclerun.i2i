import logging

def logInfo(message):
    print(message)
    logging.info(message)

def logError(message):
    print(f"❌ {message}")
    logging.error(message)

def logWarn(message):
    print(f"⚠️ {message}")
    logging.warning(message)

def logDebug(message):
    if logging.getLogger().isEnabledFor(logging.DEBUG):
        print(f"[DEBUG] {message}")
    logging.debug(message)