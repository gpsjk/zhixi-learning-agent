"""把 Streamlit Cloud 的 secrets 注入为环境变量。

本地开发仍使用 `.env`（python-dotenv 读取）；部署到 Streamlit Community Cloud 时，
在网页 Secrets 里填写的键值会通过本模块写入 os.environ，
因此 llm_service 等处无需改动即可读到 OPENAI_API_KEY 等配置。
"""

import os


def bridge_streamlit_secrets() -> None:
    """将 st.secrets 中的标量值复制到环境变量，已存在的变量不覆盖。"""
    try:
        import streamlit as st

        for key, value in st.secrets.items():
            if isinstance(value, (str, int, float, bool)):
                os.environ.setdefault(str(key), str(value))
    except Exception:
        # 未配置 secrets（本地开发）或不在 Streamlit 运行时中，保持静默。
        return
