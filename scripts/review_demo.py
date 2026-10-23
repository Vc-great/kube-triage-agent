#!/usr/bin/env python3
"""复用 Skills Demo 隔离启动器；默认端口 12072/13072/15472。"""

from skills_demo import main

if __name__ == "__main__":
    try:
        main(reviewer=True)
    except KeyboardInterrupt:
        pass
