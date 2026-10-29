#!/usr/bin/env python3
"""Issue #69 Phase A：复用隔离启动器，默认 12069/13069/15469；不启用 Phase B。"""

from skills_demo import main

if __name__ == "__main__":
    try:
        main(notes=True)
    except KeyboardInterrupt:
        pass
