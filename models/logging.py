import asyncio
import datetime
import json
import logging
import sys
from typing import Dict, Optional, Set
from fastapi import WebSocket, WebSocketDisconnect


class StreamToLogger:
    def __init__(self, logger_instance, log_level=logging.INFO):
        self.logger = logger_instance
        self.log_level = log_level
        self.linebuf = ''

    def write(self, buf):
        try:
            temp_linebuf = self.linebuf + buf
            self.linebuf = ''
            for line in temp_linebuf.splitlines(True):
                if line.endswith(('\n', '\r')):
                    self.logger.log(self.log_level, line.rstrip())
                else:
                    self.linebuf += line
        except Exception as e:
            print(f"StreamToLogger 错误: {e}", file=sys.__stderr__)

    def flush(self):
        try:
            if self.linebuf != '':
                self.logger.log(self.log_level, self.linebuf.rstrip())
            self.linebuf = ''
        except Exception as e:
            print(f"StreamToLogger Flush 错误: {e}", file=sys.__stderr__)

    def isatty(self):
        return False


class WebSocketConnectionManager:
    def __init__(self):
        self.active_connections: Dict[str, WebSocket] = {}
        self._cleanup_task: Optional[asyncio.Task] = None
        self._is_shutting_down = False
        self._lock = asyncio.Lock()

    async def connect(self, client_id: str, websocket: WebSocket):
        """连接新的WebSocket客户端"""
        try:
            await websocket.accept()

            async with self._lock:
                if self._is_shutting_down:
                    await websocket.close(code=1001, reason="Server is shutting down")
                    return

                self.active_connections[client_id] = websocket

            logger = logging.getLogger("AIStudioProxyServer")
            logger.info(f"WebSocket 日志客户端已连接: {client_id}")

            # 发送欢迎消息
            try:
                await websocket.send_text(json.dumps({
                    "type": "connection_status",
                    "status": "connected",
                    "message": "已连接到实时日志流。",
                    "timestamp": datetime.datetime.now().isoformat()
                }))
            except Exception as e:
                logger.warning(f"向 WebSocket 客户端 {client_id} 发送欢迎消息失败: {e}")
                await self.disconnect(client_id)

        except Exception as e:
            logger = logging.getLogger("AIStudioProxyServer")
            logger.error(f"WebSocket 连接失败 {client_id}: {e}")
            await self.disconnect(client_id)

    async def disconnect(self, client_id: str):
        """断开WebSocket客户端连接"""
        async with self._lock:
            if client_id in self.active_connections:
                websocket = self.active_connections.pop(client_id)
                try:
                    if not websocket.client_state.DISCONNECTED:
                        await websocket.close()
                except Exception as e:
                    logger = logging.getLogger("AIStudioProxyServer")
                    logger.warning(f"关闭 WebSocket 连接 {client_id} 时出错: {e}")

                logger = logging.getLogger("AIStudioProxyServer")
                logger.info(f"WebSocket 日志客户端已断开: {client_id}")

    async def broadcast(self, message: str):
        """向所有活跃连接广播消息"""
        if self._is_shutting_down:
            return

        async with self._lock:
            if not self.active_connections:
                return

            # 创建连接副本以避免在迭代时修改字典
            active_conns_copy = list(self.active_connections.items())

        disconnected_clients = []
        logger = logging.getLogger("AIStudioProxyServer")

        # 并发发送消息以提高性能
        async def send_to_client(client_id: str, connection: WebSocket):
            try:
                await connection.send_text(message)
                return None
            except WebSocketDisconnect:
                logger.info(f"[WS Broadcast] 客户端 {client_id} 在广播期间断开连接。")
                return client_id
            except RuntimeError as e:
                if "Connection is closed" in str(e) or "WebSocket is closed" in str(e):
                    logger.info(f"[WS Broadcast] 客户端 {client_id} 的连接已关闭。")
                    return client_id
                else:
                    logger.error(f"广播到 WebSocket {client_id} 时发生运行时错误: {e}")
                    return client_id
            except Exception as e:
                logger.error(f"广播到 WebSocket {client_id} 时发生未知错误: {e}")
                return client_id

        # 并发发送消息
        tasks = [send_to_client(client_id, connection) for client_id, connection in active_conns_copy]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # 收集需要断开的客户端
        for result in results:
            if isinstance(result, str):  # 客户端ID
                disconnected_clients.append(result)
            elif isinstance(result, Exception):
                logger.error(f"广播任务异常: {result}")

        # 清理断开的连接
        if disconnected_clients:
            for client_id_to_remove in disconnected_clients:
                await self.disconnect(client_id_to_remove)

    async def cleanup_stale_connections(self):
        """清理过期的连接"""
        if self._is_shutting_down:
            return

        async with self._lock:
            stale_clients = []
            for client_id, websocket in self.active_connections.items():
                try:
                    # 检查连接状态
                    if websocket.client_state.DISCONNECTED:
                        stale_clients.append(client_id)
                except Exception:
                    # 如果无法检查状态，认为连接已断开
                    stale_clients.append(client_id)

        # 清理过期连接
        for client_id in stale_clients:
            await self.disconnect(client_id)

        if stale_clients:
            logger = logging.getLogger("AIStudioProxyServer")
            logger.info(f"清理了 {len(stale_clients)} 个过期的 WebSocket 连接")

    async def start_cleanup_task(self):
        """启动定期清理任务"""
        if self._cleanup_task is None or self._cleanup_task.done():
            self._cleanup_task = asyncio.create_task(self._periodic_cleanup())

    async def _periodic_cleanup(self):
        """定期清理任务"""
        while not self._is_shutting_down:
            try:
                await asyncio.sleep(30)  # 每30秒清理一次
                await self.cleanup_stale_connections()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger = logging.getLogger("AIStudioProxyServer")
                logger.error(f"定期清理任务出错: {e}")

    async def shutdown(self):
        """关闭连接管理器"""
        self._is_shutting_down = True

        # 取消清理任务
        if self._cleanup_task and not self._cleanup_task.done():
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass

        # 关闭所有连接
        async with self._lock:
            disconnect_tasks = []
            for client_id in list(self.active_connections.keys()):
                disconnect_tasks.append(self.disconnect(client_id))

            if disconnect_tasks:
                await asyncio.gather(*disconnect_tasks, return_exceptions=True)

        logger = logging.getLogger("AIStudioProxyServer")
        logger.info("WebSocket 连接管理器已关闭")

    def get_connection_count(self) -> int:
        """获取活跃连接数"""
        return len(self.active_connections)


class WebSocketLogHandler(logging.Handler):
    def __init__(self, manager: WebSocketConnectionManager):
        super().__init__()
        self.manager = manager
        self.formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
        self._pending_tasks: Set[asyncio.Task] = set()

    def emit(self, record: logging.LogRecord):
        """发送日志记录到WebSocket连接"""
        if not self.manager or self.manager._is_shutting_down:
            return

        if not self.manager.active_connections:
            return

        try:
            log_entry_str = self.format(record)
            try:
                current_loop = asyncio.get_running_loop()
                # 创建任务并跟踪它
                task = current_loop.create_task(self._safe_broadcast(log_entry_str))
                self._pending_tasks.add(task)
                task.add_done_callback(self._pending_tasks.discard)
            except RuntimeError:
                # 没有运行的事件循环，忽略
                pass
        except Exception as e:
            print(f"WebSocketLogHandler 错误: 广播日志失败 - {e}", file=sys.__stderr__)

    async def _safe_broadcast(self, message: str):
        """安全地广播消息，处理异常"""
        try:
            await self.manager.broadcast(message)
        except Exception as e:
            # 避免在日志处理器中记录日志，防止递归
            print(f"WebSocket 广播失败: {e}", file=sys.__stderr__)

    async def close_async(self):
        """异步关闭处理器"""
        # 等待所有待处理的任务完成
        if self._pending_tasks:
            await asyncio.gather(*self._pending_tasks, return_exceptions=True)

        # 关闭连接管理器
        if self.manager:
            await self.manager.shutdown()

    def close(self):
        """同步关闭处理器（logging.Handler接口）"""
        try:
            # 尝试在当前事件循环中运行异步关闭
            loop = asyncio.get_running_loop()
            loop.create_task(self.close_async())
        except RuntimeError:
            # 没有运行的事件循环，直接关闭
            pass
        super().close()