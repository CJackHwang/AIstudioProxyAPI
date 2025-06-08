# browser_utils/response_modifiers.py
import copy
import logging
from typing import List, Tuple, Any

def modify_model_list_data(original_model_data_container: List, models_to_inject_config: List, logger: logging.Logger) -> Tuple[List, bool]:
    """
    修改原始模型列表数据，注入自定义模型或更新现有模型。

    Args:
        original_model_data_container: 从原始网络响应解析出来的、包含模型列表的整个数据结构。
                                       例如：[[['models/gemini-pro', ...], ['models/gemini-flash', ...]]]
        models_to_inject_config: 从 config/custom_models.json 加载并解析后的模型配置列表。
        logger: 一个 logging.Logger 实例，用于记录日志。

    Returns:
        一个元组：
        1. 修改后的模型数据容器 (与 original_model_data_container 结构相同)。
        2. 一个布尔值，指示是否对数据进行了任何修改 (True 表示已修改，False 表示未修改)。
    """
    # 确定模型数据在列表中的索引 (根据您提供的原始响应数据进行精确调整)
    # 原始响应数据: [[['models/gemini-2.5-pro-preview-06-05', None, '2.5-preview-06-05', 'Gemini 2.5 Pro Preview', ..., ['generateContent', 'countTokens', ...]], ...]]
    # 观察数据，模型名称在内部列表的第 0 个位置
    # 显示名称在内部列表的第 3 个位置
    # 描述在内部列表的第 4 个位置
    # 支持的方法列表在内部列表的第 7 个位置
    NAME_IDX = 0
    DISPLAY_NAME_IDX = 3
    DESC_IDX = 4
    METHODS_IDX = 7

    if isinstance(original_model_data_container, list) and \
       len(original_model_data_container) > 0 and \
       isinstance(original_model_data_container[0], list):
        modified_json_container = copy.deepcopy(original_model_data_container)
        models_array = modified_json_container[0]
    else:
        logger.error("Unexpected JSON structure: models array not found at the expected position (original_model_data_container[0]). Aborting modification.")
        return original_model_data_container, False

    if not isinstance(models_array, list):
        logger.error("Extracted models_array is not a list. Aborting modification.")
        return original_model_data_container, False

    modification_made = False
    template_model = None

    required_indices = {NAME_IDX, DISPLAY_NAME_IDX, DESC_IDX, METHODS_IDX}
    max_required_index = max(required_indices) if required_indices else 0

    for m in models_array:
        if not isinstance(m, list):
            continue
        if len(m) <= max_required_index:
            logger.debug(f"   Skipping model (length insufficient): {m[NAME_IDX] if len(m) > NAME_IDX else 'Unknown Name'}")
            continue
        if not isinstance(m[NAME_IDX], str) or not isinstance(m[METHODS_IDX], list):
            logger.debug(f"   Skipping model (type mismatch at NAME_IDX or METHODS_IDX): {m[NAME_IDX]}")
            continue
        if not isinstance(m[DISPLAY_NAME_IDX], (str, type(None))) or \
           not isinstance(m[DESC_IDX], (str, type(None))):
            logger.debug(f"   Skipping model (type mismatch at DISPLAY_NAME_IDX or DESC_IDX): {m[NAME_IDX]}")
            continue
        if 'flash' in m[NAME_IDX] or 'pro' in m[NAME_IDX]:
            template_model = m
            logger.info(f"   Found preferred template model: {m[NAME_IDX]}")
            break

    if not template_model:
        for m in models_array:
            if not isinstance(m, list):
                continue
            if len(m) <= max_required_index:
                continue
            if not isinstance(m[NAME_IDX], str) or not isinstance(m[METHODS_IDX], list):
                continue
            if not isinstance(m[DISPLAY_NAME_IDX], (str, type(None))) or \
               not isinstance(m[DESC_IDX], (str, type(None))):
                continue
            template_model = m
            logger.info(f"   Found fallback template model: {m[NAME_IDX]}")
            break

    template_name = template_model[NAME_IDX] if template_model and len(template_model) > NAME_IDX else 'unknown'
    if template_model:
        logger.info(f"   Using template: {template_name}")
        logger.info(f"   Template model details: Name='{template_model[NAME_IDX]}', DisplayName='{template_model[DISPLAY_NAME_IDX]}', Desc='{template_model[DESC_IDX]}', Methods='{template_model[METHODS_IDX]}'")
    else:
        logger.warning('Could not find a suitable template model array. Cannot inject new models, but can update existing ones.')

    for model_to_inject in reversed(models_to_inject_config):
        model_exists = False
        for model in models_array:
            if isinstance(model, list) and len(model) > NAME_IDX and model[NAME_IDX] == model_to_inject["name"]:
                model_exists = True
                break
        if not model_exists:
            if not template_model:
                logger.warning(f"Cannot inject {model_to_inject['name']}: No template found.")
                continue
            new_model = copy.deepcopy(template_model)
            
            if len(new_model) > NAME_IDX:
                new_model[NAME_IDX] = model_to_inject["name"]
            else:
                while len(new_model) <= NAME_IDX:
                    new_model.append(None)
                new_model[NAME_IDX] = model_to_inject["name"]
            
            if len(new_model) > DISPLAY_NAME_IDX:
                new_model[DISPLAY_NAME_IDX] = model_to_inject["displayName"]
            else:
                while len(new_model) <= DISPLAY_NAME_IDX:
                    new_model.append(None)
                new_model[DISPLAY_NAME_IDX] = model_to_inject["displayName"]
            
            if len(new_model) > DESC_IDX:
                new_model[DESC_IDX] = f"{model_to_inject['description']} (Structure based on {template_name})"
            else:
                while len(new_model) <= DESC_IDX:
                    new_model.append(None)
                new_model[DESC_IDX] = f"{model_to_inject['description']} (Structure based on {template_name})"
            
            if len(new_model) > METHODS_IDX:
                if not isinstance(new_model[METHODS_IDX], list) or not new_model[METHODS_IDX]:
                    new_model[METHODS_IDX] = ["generateContent", "countTokens","createCachedContent","batchGenerateContent"]
            else:
                while len(new_model) <= METHODS_IDX:
                    new_model.append(None)
                new_model[METHODS_IDX] = ["generateContent", "countTokens","createCachedContent","batchGenerateContent"]
            
            models_array.insert(0, new_model)
            modification_made = True
            logger.info(f"Successfully INJECTED: {model_to_inject['displayName']}")
        else:
            existing_model = next((model for model in models_array if isinstance(model, list) and len(model) > NAME_IDX and model[NAME_IDX] == model_to_inject["name"]), None)
            if existing_model and len(existing_model) > DISPLAY_NAME_IDX:
                current_display_name = existing_model[DISPLAY_NAME_IDX]
                target_display_name = model_to_inject["displayName"]
                if current_display_name != target_display_name:
                    existing_model[DISPLAY_NAME_IDX] = target_display_name
                    modification_made = True
                    logger.info(f"Updated displayName for existing model {model_to_inject['name']} to: {target_display_name}")
    
    return modified_json_container, modification_made