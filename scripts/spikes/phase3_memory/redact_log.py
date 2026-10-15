"""Remove synthetic credentials from Aegra spike logs before displaying/saving."""

import os
import sys

secrets = [os.environ.get(name, "") for name in ("DEMO_API_TOKEN", "PHASE30_DB_PASSWORD")]
for line in sys.stdin:
    for secret in secrets:
        if secret:
            line = line.replace(secret, "[REDACTED]")
    sys.stdout.write(line)
    sys.stdout.flush()
