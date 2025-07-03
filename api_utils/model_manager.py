"""
模型管理器
提供线程安全的模型切换和状态管理
"""

import asyncio
import logging
from typing import Optional, Dict, Any, List, Set
from contextlib import asynccontextmanager
from playwright.async_api import Page as AsyncPage

from .state_manager import get_state_manager

logger = logging.getLogger("AIStudioProxyServer")


class ModelManager:
    """模型管理器，确保模型切换的原子性和一致性"""

    def __init__(self):
        self._state_manager = get_state_manager()
        self._switching_in_progress = False
        self._switch_lock = asyncio.Lock()

    async def get_current_model_id(self) -> Optional[str]:
        """获取当前模型ID"""
        return await self._state_manager.get_current_model_id()

    async def get_model_list(self) -> List[Dict[str, Any]]:
        """获取模型列表"""
        return await self._state_manager.get_model_list()

    async def get_excluded_model_ids(self) -> Set[str]:
        """获取排除的模型ID"""
        return await self._state_manager.get_excluded_model_ids()

    async def is_valid_model(self, model_id: str) -> bool:
        """检查模型ID是否有效"""
        model_list = await self.get_model_list()
        excluded_ids = await self.get_excluded_model_ids()
        
        if model_id in excluded_ids:
            return False
        
        valid_model_ids = [m.get("id") for m in model_list if m.get("id")]
        return model_id in valid_model_ids

    async def needs_model_switch(self, target_model_id: str) -> bool:
        """检查是否需要切换模型"""
        current_model_id = await self.get_current_model_id()
        return current_model_id != target_model_id

    @asynccontextmanager
    async def model_switch_context(self, req_id: str):
        """模型切换上下文管理器"""
        async with self._switch_lock:
            if self._switching_in_progress:
                logger.warning(f"[{req_id}] 模型切换已在进行中，等待完成...")
            
            self._switching_in_progress = True
            logger.info(f"[{req_id}] 开始模型切换操作")
            
            try:
                yield self
            finally:
                self._switching_in_progress = False
                logger.info(f"[{req_id}] 模型切换操作完成")

    async def switch_model_safe(
        self, 
        page: AsyncPage, 
        target_model_id: str, 
        req_id: str
    ) -> bool:
        """安全地切换模型"""
        async with self.model_switch_context(req_id):
            # 再次检查是否需要切换（可能在等待锁期间已经切换了）
            if not await self.needs_model_switch(target_model_id):
                logger.info(f"[{req_id}] 模型已经是目标模型 {target_model_id}，无需切换")
                return True

            # 验证目标模型是否有效
            if not await self.is_valid_model(target_model_id):
                logger.error(f"[{req_id}] 目标模型 {target_model_id} 无效或被排除")
                return False

            current_model_id = await self.get_current_model_id()
            logger.info(f"[{req_id}] 准备切换模型: {current_model_id} -> {target_model_id}")

            try:
                # 执行实际的模型切换
                from browser_utils import switch_ai_studio_model
                switch_success = await switch_ai_studio_model(page, target_model_id, req_id)
                
                if switch_success:
                    # 原子性地更新模型状态
                    await self._state_manager.set_current_model_id(target_model_id)
                    logger.info(f"[{req_id}] ✅ 模型切换成功: {target_model_id}")
                    return True
                else:
                    logger.error(f"[{req_id}] ❌ 模型切换失败: {target_model_id}")
                    return False

            except Exception as e:
                logger.error(f"[{req_id}] 模型切换过程中发生异常: {e}", exc_info=True)
                return False

    async def update_model_list_safe(
        self, 
        model_list: List[Dict[str, Any]], 
        raw_json: Optional[List[Any]] = None
    ) -> None:
        """安全地更新模型列表"""
        async with self._switch_lock:
            await self._state_manager.set_model_list(model_list, raw_json)
            logger.info(f"模型列表已更新: {len(model_list)} 个模型")

    async def update_excluded_models_safe(self, excluded_ids: Set[str]) -> None:
        """安全地更新排除的模型ID"""
        async with self._switch_lock:
            await self._state_manager.set_excluded_model_ids(excluded_ids)
            logger.info(f"排除模型列表已更新: {len(excluded_ids)} 个模型")

    async def set_current_model_from_page(self, model_id: str, req_id: str = "system") -> None:
        """从页面检测设置当前模型（不执行切换操作）"""
        async with self._switch_lock:
            current_model_id = await self.get_current_model_id()
            if current_model_id != model_id:
                await self._state_manager.set_current_model_id(model_id)
                logger.info(f"[{req_id}] 从页面检测更新当前模型: {current_model_id} -> {model_id}")

    async def validate_model_request(self, requested_model: str, req_id: str) -> str:
        """验证模型请求并返回模型ID"""
        if not requested_model:
            raise ValueError(f"[{req_id}] 模型名称不能为空")

        # 提取模型ID（移除 models/ 前缀）
        model_id = requested_model.split('/')[-1] if '/' in requested_model else requested_model
        
        # 验证模型是否有效
        if not await self.is_valid_model(model_id):
            model_list = await self.get_model_list()
            valid_model_ids = [m.get("id") for m in model_list if m.get("id")]
            raise ValueError(
                f"[{req_id}] 无效的模型 '{model_id}'。可用模型: {', '.join(valid_model_ids)}"
            )

        return model_id

    async def get_model_info(self, model_id: str) -> Optional[Dict[str, Any]]:
        """获取模型信息"""
        model_list = await self.get_model_list()
        for model in model_list:
            if model.get("id") == model_id:
                return model
        return None

    async def is_switching_in_progress(self) -> bool:
        """检查是否有模型切换正在进行"""
        return self._switching_in_progress

    async def wait_for_switch_completion(self, timeout: float = 30.0) -> None:
        """等待模型切换完成"""
        start_time = asyncio.get_event_loop().time()
        while self._switching_in_progress:
            if asyncio.get_event_loop().time() - start_time > timeout:
                raise asyncio.TimeoutError("等待模型切换完成超时")
            await asyncio.sleep(0.1)

    async def get_model_statistics(self) -> Dict[str, Any]:
        """获取模型统计信息"""
        model_list = await self.get_model_list()
        excluded_ids = await self.get_excluded_model_ids()
        current_model_id = await self.get_current_model_id()
        
        return {
            "total_models": len(model_list),
            "excluded_models": len(excluded_ids),
            "available_models": len(model_list) - len(excluded_ids),
            "current_model": current_model_id,
            "switching_in_progress": self._switching_in_progress,
        }


# 全局模型管理器实例
_model_manager: Optional[ModelManager] = None


def get_model_manager() -> ModelManager:
    """获取全局模型管理器实例"""
    global _model_manager
    if _model_manager is None:
        _model_manager = ModelManager()
    return _model_manager


# 便捷函数
async def switch_model_safe(page: AsyncPage, target_model_id: str, req_id: str) -> bool:
    """安全地切换模型的便捷函数"""
    return await get_model_manager().switch_model_safe(page, target_model_id, req_id)


async def get_current_model_safe() -> Optional[str]:
    """安全地获取当前模型ID的便捷函数"""
    return await get_model_manager().get_current_model_id()


async def validate_model_request_safe(requested_model: str, req_id: str) -> str:
    """安全地验证模型请求的便捷函数"""
    return await get_model_manager().validate_model_request(requested_model, req_id)


async def is_model_switch_needed(target_model_id: str) -> bool:
    """检查是否需要模型切换的便捷函数"""
    return await get_model_manager().needs_model_switch(target_model_id)
