# 云端部署说明（Streamlit Community Cloud）

本目录是可直接推送的仓库副本。本地运行方式不变（`start.bat`）；上云时密钥走 Streamlit Secrets。

仓库地址：<https://github.com/gpsjk/zhixi-learning-agent>

## 一、仓库内容约定

| 文件 | 作用 |
| --- | --- |
| `app.py` | Streamlit 入口 |
| `requirements.txt` | 云端依赖，Cloud 自动安装 |
| `.streamlit/config.toml` | 主题配置（已移除本地 `server.address`，云端由平台绑定端口） |
| `cloud_secrets.py` | 把 Cloud 的 Secrets 注入 `os.environ`，使 `llm_service` 无需改动即可读取 |
| `data/mistakes.db` | 演示用 SQLite 数据 |

> 注意：Cloud 的容器文件系统**重启即重置**，演示期间新写入的错题不会持久保存。
> 需要长期留存请改用外部数据库（如 Postgres / Supabase）。

## 二、部署步骤

1. 打开一键预填的部署链接（仓库、分支、入口文件都已带上）：

   <https://share.streamlit.io/deploy?repository=gpsjk/zhixi-learning-agent&branch=main&mainModule=app.py>

2. 用 GitHub 账号登录并授权 Streamlit。
3. 在 **Advanced settings → Secrets** 粘贴密钥（见第三节），然后点 **Deploy**。
4. 构建完成后得到固定地址 `https://zhixi-learning-agent.streamlit.app`。

## 三、Secrets 配置

```toml
OPENAI_API_KEY = "sk-xxxxxxxxxxxxxxxx"
OPENAI_BASE_URL = "https://api.deepseek.com"
OPENAI_MODEL = "deepseek-flash"
OPENAI_VISION_MODEL = ""
```

- `OPENAI_MODEL` 必须是账号下真实存在的模型。DeepSeek 官方当前可用的是
  `deepseek-flash` 与 `deepseek-v4-pro`（旧的 `deepseek-v4-flash` 已不存在）。
- DeepSeek 官方接口**不提供多模态模型**，因此 `OPENAI_VISION_MODEL` 在 DeepSeek 下只能留空，
  留空时「拍照识题」会提示不可用，其余功能不受影响。
  如需拍照识题，请换用带视觉能力的兼容服务（如阿里云百炼 `qwen-vl-max`、智谱 `glm-4v`），
  并同时修改 `OPENAI_BASE_URL` 与 `OPENAI_API_KEY`。
- 留空 `OPENAI_API_KEY` 时应用进入**演示模式**：错题本、复习训练、统计摘要可用，
  模型相关结果为演示数据。

## 四、修改配置

- 改密钥：应用页面右上角 → **Settings → Secrets**，保存后应用自动重启。
- 改代码：push 到 GitHub `main` 分支，Cloud 自动重新部署。
- 查看日志：应用页面右下角 **Manage app**。

## 五、本地与云端的差异

| 项目 | 本地 | 云端 |
| --- | --- | --- |
| 密钥来源 | `.env` | Settings → Secrets |
| 数据库 | `data/mistakes.db` 持久 | 容器内、重启丢失 |
| 启动 | `start.bat` | 平台自动 `streamlit run app.py` |
