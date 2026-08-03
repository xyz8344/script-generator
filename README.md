# 🎬 爆款脚本生成器

AI 驱动的短视频脚本创作工具。输入赛道 + 话题，一键生成含分镜、文案、BGM 的完整拍摄脚本。

## 功能

- 📱 支持抖音、小红书、B站、视频号
- 🎭 5 种脚本风格：干货型、故事型、情绪型、悬念型、反常识型
- ⏱️ 30秒 / 60秒 / 90秒 / 3分钟
- 📝 完整分镜表格 + 拍摄建议 + 发布建议
- 💾 复制全文 / 下载 Markdown

## 本地运行

```bash
# 1. 安装依赖
pip install -r requirements.txt

# 2. 配置 API Key
# 复制 .env.example 为 .env，填入你的 DeepSeek API Key

# 3. 启动
streamlit run app.py
```

浏览器打开 http://localhost:8501

## 环境变量

复制 `.env.example` 为 `.env`：

```
ANTHROPIC_BASE_URL=https://api.deepseek.com/anthropic
ANTHROPIC_AUTH_TOKEN=你的API-Key
MODEL=deepseek-v4-pro
```

## 技术栈

- **前端**：Streamlit
- **AI**：DeepSeek API（Anthropic 兼容接口）
- **语言**：Python 3.10+
