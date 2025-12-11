#!/bin/bash

# 定义颜色变量以便复用
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

set -e

echo -e "${GREEN}==> 正在更新并重启服务...${NC}"

# 获取脚本所在的目录，并切换到项目根目录
SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" &> /dev/null && pwd)
cd "$SCRIPT_DIR/.."

echo -e "${YELLOW}--> 步骤 1/4: 拉取最新的代码...${NC}"
git pull

cd "$SCRIPT_DIR"

echo -e "${YELLOW}--> 步骤 2/4: 停止并移除旧的容器...${NC}"
docker compose down

echo -e "${YELLOW}--> 步骤 3/4: 使用 Docker Compose 构建并启动新容器...${NC}"
# docker compose up -d --build
# # -p 参数指定项目名称，例如叫 "ai-studio-proxy"
docker compose -p ai-studio-proxy up -d --build

echo -e "${YELLOW}--> 步骤 4/4: 显示当前运行的容器状态...${NC}"
docker compose ps

echo -e "${GREEN}==> 更新完成！${NC}"
