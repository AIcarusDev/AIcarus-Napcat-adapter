#!/usr/bin/env python3
"""AIcarus Napcat Adapter v2.0.0 启动脚本.

运行 AIcarus-Message-Protocol v2.0.0 版本的适配器
"""

import sys

from src.logger import logger  # 现在可以尝试导入 Adapter 自己的 logger
from src.main_aicarus import main

if __name__ == "__main__":
    logger.info("AIcarus Napcat Adapter v2.0.0 正在通过 run_adapter.py 启动...")
    try:
        import asyncio

        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("程序被用户中断。")
    except Exception:
        logger.exception("AIcarus Napcat Adapter v2.0.0 运行时发生严重错误:")
        sys.exit(1)
    finally:
        logger.info("AIcarus Napcat Adapter v2.0.0 执行完毕。")
