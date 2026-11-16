# 云端部署说明（Streamlit Community Cloud）

本目录是可直接推送的仓库副本。本地运行方式不变（`start.bat`）；上云时密钥走 Streamlit Secrets。

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

1. 新建 GitHub 仓库（Public 或 Private 均可），把本目录所有文件推送到 `main` 分支。
2. 打开 <https://share.streamlit.io>，用 GitHub 账号登录并授权。
3. 点击 **Create app** → **Deploy a public app from GitHub**：
   - Repository：选择刚建的仓库
   - Branch：`main`
   - Main file path：`app.py`
   - Python version：`3.12`
4. 展开 **Advanced settings → Secrets**，粘贴下面的配置（换成真实 Key）：

```toml
OPENAI_API_KEY = "sk-xxxxxxxxxxxxxxxx"
OPENAI_BASE_URL = "https://api.deepseek.com"
OPENAI_MODEL = "deepseek-v4-flash"
OPENAI_VISION_MODEL = "deepseek-vl"
```

5. 点击 **Deploy**，等待构建完成即可获得固定的 `https://<app名>.streamlit.app` 地址。

`OPENAI_VISION_MODEL` 必须使用支持图片输入的多模态模型，否则拍照识题会提示不可用，
其余功能（错题本、复习训练、统计）不受影响。留空 `OPENAI_API_KEY` 时应用进入演示模式。

## 三、修改配置

- 改密钥：应用页面右上角 → **Settings → Secrets**，保存后应用会自动重启。
- 改代码：push 到 GitHub `main` 分支，Cloud 自动重新部署。
- 查看日志：应用页面右下角 **Manage app**。

## 四、本地与云端的差异

| 项目 | 本地 | 云端 |
| --- | --- | --- |
| 密钥来源 | `.env` | Settings → Secrets |
| 数据库 | `data/mistakes.db` 持久 | 容器内、重启丢失 |
| 启动 | `start.bat` | 平台自动 `streamlit run app.py` |
