RTP_EVALUATION = True

import logging
import sys
from os import path
LOG_DIR = "chrome-audit-logs"
LOG_FILE_TEMPLATE = path.join(LOG_DIR, "chrome-audit-{0}.log")

CSV_DIR = "neo4j-csvs"
DELIM=";"


if RTP_EVALUATION:
    stream = open('/dev/null', 'w')
else:
    stream = sys.stdout

SCRIPT_CACHE = "script-cache"
LOG_LEVEL = logging.INFO
logging.basicConfig(stream=stream, level=LOG_LEVEL)



