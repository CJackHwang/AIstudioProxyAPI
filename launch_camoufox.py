#!/usr/bin/env python3
# launch_camoufox.py
from dotenv import load_dotenv

# 提前加载 .env 文件，以确保后续导入的模块能获取到正确的环境变量
load_dotenv()

from launcher.runner import Launcher

if __name__ == "__main__":
    Launcher().run()
