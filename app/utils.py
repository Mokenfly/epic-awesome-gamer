# -*- coding: utf-8 -*-
from __future__ import annotations
import os
import sys
import asyncio
from pathlib import Path
from zoneinfo import ZoneInfo
from loguru import logger
# 修正导入：直接从 settings 导入，不要加 app. 前缀
from settings import settings

def timezone_filter(record):
    record["time"] = record["time"].astimezone(ZoneInfo("Asia/Shanghai"))
    return record

def patch_aihubmix_bypass():
    """AiHubMix 终极补丁：绕过 File API，改用 Inline Data (Base64)"""
    if not settings.GEMINI_API_KEY:
        return
    
    try:
        from google import genai
        from google.genai import types
        
        # 1. 自动处理 AiHubMix Gemini Native 路径
        orig_init = genai.Client.__init__
        def new_init(self, *args, **kwargs):
            # 兼容处理：无论 Settings 里是 SecretStr 还是 str 都能读取
            if hasattr(settings.GEMINI_API_KEY, 'get_secret_value'):
                api_key = settings.GEMINI_API_KEY.get_secret_value()
            else:
                api_key = str(settings.GEMINI_API_KEY)
            
            kwargs['api_key'] = api_key
            
            # 清理并对齐 AiHubMix 的 Gemini 原生接口路径
            base_url = settings.GEMINI_BASE_URL.rstrip('/')
            if base_url.endswith('/v1'):
                base_url = base_url[:-3]
            if not base_url.endswith('/gemini'):
                base_url = f"{base_url}/gemini"
            
            kwargs['http_options'] = types.HttpOptions(base_url=base_url)
            logger.info(f"🚀 AiHubMix 终极补丁激活 | 模型: {settings.GEMINI_MODEL} | 地址: {base_url}")
            orig_init(self, *args, **kwargs)
        genai.Client.__init__ = new_init

        # 2. 魔法：缓存文件内容并重定向请求
        file_cache = {}

        async def patched_upload(self_files, file, **kwargs):
            """拦截上传，将文件存入内存"""
            if hasattr(file, 'read'):
                content = file.read()
            elif isinstance(file, (str, Path)):
                with open(file, 'rb') as f:
                    content = f.read()
            else:
                content = bytes(file)
            
            if asyncio.iscoroutine(content):
                content = await content
            
            file_id = f"bypass_{id(content)}"
            file_cache[file_id] = content
            # 返回伪造的文件对象，骗过上层逻辑
            return types.File(name=file_id, uri=file_id, mime_type="image/png")

        orig_generate = genai.models.AsyncModels.generate_content
        async def patched_generate(self_models, model, contents, **kwargs):
            """拦截识别，将文件引用替换为 Base64"""
            from google.genai._common import _contents_to_list
            normalized = _contents_to_list(contents)
            
            for content in normalized:
                for i, part in enumerate(content.parts):
                    # 如果检测到被拦截的文件 ID，则转换格式为 Base64
                    if part.file_data and part.file_data.file_uri in file_cache:
                        data = file_cache[part.file_data.file_uri]
                        content.parts[i] = types.Part.from_bytes(data=data, mime_type="image/png")
            
            return await orig_generate(self_models, model, normalized, **kwargs)

        # 挂载补丁
        genai.files.AsyncFiles.upload = patched_upload
        genai.models.AsyncModels.generate_content = patched_generate
        
    except Exception as e:
        logger.error(f"终极补丁加载失败: {e}")

def init_log(**sink_channel):
    # 强制注入中转补丁
    patch_aihubmix_bypass()
    
    log_level = os.getenv("LOG_LEVEL", "DEBUG").upper()
    logger.remove()
    logger.add(sink=sys.stdout, level=log_level, filter=timezone_filter)
    return logger

# 确保最后一行只有函数调用，不要有注释
init_log()
