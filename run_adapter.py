#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AIcarus Napcat Adapter v1.4.0 启动脚本
运行 AIcarus-Message-Protocol v1.4.0 版本的适配器
"""

import sys

from src.main_aicarus import main
from src.logger import logger  # 现在可以尝试导入 Adapter 自己的 logger

if __name__ == "__main__":
    logger.info("AIcarus Napcat Adapter v1.4.0 正在通过 run_adapter_v1_4_0.py 启动...")
    try:
        import asyncio

        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("程序被用户中断。")
    except Exception:
        logger.exception("AIcarus Napcat Adapter v1.4.0 运行时发生严重错误:")
        sys.exit(1)
    finally:
        logger.info("AIcarus Napcat Adapter v1.4.0 执行完毕。")
