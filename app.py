"""
🎬 爆款脚本生成器 — AI 驱动的短视频脚本创作工具
输入赛道 + 话题，一键生成可直接拍摄的专业脚本
"""
import streamlit as st
import requests
import os
import json
from datetime import datetime
from dotenv import load_dotenv

# --- 加载配置（优先级：Streamlit Secrets > 环境变量 > .env > 默认值）---
load_dotenv()

def get_config(key: str, default: str = "") -> str:
    """多来源读取配置：st.secrets > env > default"""
    try:
        return st.secrets.get(key, os.environ.get(key, default))
    except Exception:
        return os.environ.get(key, default)

ANTHROPIC_BASE_URL = get_config(
    "ANTHROPIC_BASE_URL",
    "https://api.deepseek.com/anthropic"
)
DEFAULT_API_KEY = get_config("ANTHROPIC_AUTH_TOKEN", "sk-988e6b9c5c3742d5a3ee678b5d3e6348")
MODEL = get_config("MODEL", "deepseek-v4-pro")

# --- 页面配置 ---
st.set_page_config(
    page_title="🎬 爆款脚本生成器",
    page_icon="🎬",
    layout="wide",
    initial_sidebar_state="expanded",
)

# --- 自定义样式 ---
st.markdown("""
<style>
    /* 整体色调 */
    :root {
        --primary: #FF6B35;
        --bg-card: #1E1E2E;
        --text: #E0E0E8;
    }

    /* 隐藏默认header */
    #MainMenu {display: none;}
    footer {visibility: hidden;}

    /* 卡片样式 */
    .script-card {
        background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%);
        border: 1px solid #2a2a4a;
        border-radius: 12px;
        padding: 24px;
        margin: 12px 0;
    }

    /* 脚本表格 */
    .script-table {
        width: 100%;
        border-collapse: collapse;
        margin: 16px 0;
        font-size: 0.9em;
    }
    .script-table th {
        background: #FF6B35;
        color: white;
        padding: 10px 12px;
        text-align: left;
        font-weight: 600;
    }
    .script-table td {
        padding: 10px 12px;
        border-bottom: 1px solid #2a2a4a;
        vertical-align: top;
    }
    .script-table tr:hover td {
        background: rgba(255,107,53,0.05);
    }

    /* 钩子高亮 */
    .hook-box {
        background: linear-gradient(135deg, #FF6B35 0%, #FF8F65 100%);
        color: white;
        padding: 16px 20px;
        border-radius: 8px;
        font-size: 1.1em;
        font-weight: 600;
        margin: 12px 0;
    }

    /* 信息标签 */
    .tag {
        display: inline-block;
        padding: 3px 10px;
        border-radius: 12px;
        font-size: 0.78em;
        margin: 2px 4px;
    }
    .tag-green { background: #1a3a2a; color: #7dcea0; }
    .tag-blue  { background: #1a2a3a; color: #7dcfff; }
    .tag-orange { background: #3a2010; color: #FF6B35; }

    /* 统计数字 */
    .stat-num {
        font-size: 2em;
        font-weight: 700;
        color: #FF6B35;
        line-height: 1.2;
    }
    .stat-label {
        font-size: 0.8em;
        color: #888;
    }
</style>
""", unsafe_allow_html=True)


# --- LLM 调用 ---
def call_llm(system_prompt: str, user_message: str, temperature: float = 0.85) -> str:
    """调用 DeepSeek API（Anthropic 兼容接口）"""
    api_key = st.session_state.get("user_api_key") or DEFAULT_API_KEY
    headers = {
        "Content-Type": "application/json",
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01",
    }
    payload = {
        "model": MODEL,
        "max_tokens": 8192,
        "temperature": temperature,
        "system": system_prompt,
        "messages": [
            {"role": "user", "content": user_message}
        ],
    }
    resp = requests.post(
        f"{ANTHROPIC_BASE_URL}/messages",
        headers=headers,
        json=payload,
        timeout=300,
    )
    if resp.status_code != 200:
        raise Exception(f"API 错误 ({resp.status_code}): {resp.text[:500]}")

    data = resp.json()
    for block in data["content"]:
        if block.get("type") == "text":
            return block["text"]
    return data["content"][-1].get("text", "")


# --- Prompt 模板 ---
def get_system_prompt(style: str, platform: str) -> str:
    """根据风格和平台生成系统提示词"""

    style_guides = {
        "干货型": """
- 开头直接点出「你会学到什么」，用具体数字/结果吸引人
- 结构：问题 → 原因 → 解决方案 → 行动步骤
- 语气专业但不枯燥，像朋友在教你
- 多用「你是不是也…」「其实很简单…」「关键就在于…」
- 每 15 秒给一个可执行的具体方法
""",
        "故事型": """
- 开头扔出一个冲突/悬念/反差，让人想知道后续
- 用「我/我朋友/有个客户」开场，增加真实感
- 结构：场景 → 冲突 → 转折 → 感悟 → 升华
- 有画面感的细节描写，让人能「看见」故事
- 结尾必须有情感锚点——让人想评论分享自己的经历
""",
        "情绪型": """
- 开头直接击中情绪痛点，让人产生「说的就是我」的共鸣
- 用排比、对比、设问强化情绪节奏
- 结构：情绪引爆 → 认同加深 → 观点输出 → 行动号召
- 前半段共情，后半段给力量/方法
- BGM 和画面要配合情绪起伏
""",
        "悬念型": """
- 开头抛出一个让人无法不往下看的问题
- 用「后来我才知道…」「最后的结果让我…」制造期待
- 结构：悬念 → 铺垫 → 反转 → 揭秘 → 方法论
- 在中间设置「假答案」，最后给真答案
- 节奏紧凑，每 5-8 秒推进一层信息
""",
        "反常识型": """
- 开头说出一个和大众认知完全相反的观点
- 用数据/案例/逻辑证明「你以为的其实是错的」
- 结构：颠覆认知 → 举例打脸 → 揭示真相 → 正确做法
- 语气：不卖关子、直给、有冲击力
- 让观众在评论区吵起来——观点要有争议但能自圆其说
""",
    }

    platform_guides = {
        "抖音": "- 时长 30-90 秒为主\n- 前 3 秒必须有强钩子\n- 口语化、节奏快、每句话都要有信息量\n- 结尾引导点赞/收藏/评论",
        "小红书": "- 语调轻松温暖，像和闺蜜聊天\n- 可以稍长（1-3 分钟）\n- 注重美感和氛围感\n- 结尾引导收藏和关注",
        "B站": "- 可以更长（3-10 分钟）\n- 允许一定的铺垫和展开\n- 可以加入梗和弹幕文化\n- 结构和逻辑更完整",
        "视频号": "- 偏成熟稳重，适合 30-90 秒\n- 风格介于抖音和 B 站之间\n- 注重情感共鸣和社交属性\n- 中老年友好，语速不要太快",
    }

    style_guide = style_guides.get(style, style_guides["干货型"])
    platform_guide = platform_guides.get(platform, platform_guides["抖音"])

    return f"""你是一位资深短视频编导，曾在头部 MCN 机构工作 5 年，打造过 50+ 百万粉账号。
你精通短视频脚本创作，尤其擅长【{style}】的脚本结构。

## 你的工作方式
1. 收到用户的话题和赛道后，先快速判断目标受众
2. 根据平台特性调整脚本节奏和话术
3. 严格按照指定风格输出脚本
4. 每一个画面建议都是可执行的，不是泛泛而谈

## 脚本风格要求
{style_guide}

## 平台特性
{platform_guide}

## 输出格式（严格遵守）

你必须输出如下结构的完整脚本：

### 🎣 开头钩子（0-5秒）
写出完整文案。这个钩子必须让人无法划走。

### 📝 完整分镜脚本
用 Markdown 表格输出：

| 时间段 | 画面/运镜 | 文案（完整） | BGM/音效 | 备注 |
|--------|----------|-------------|----------|------|
| 0-5s   | ... | ... | ... | ... |

表格至少包含 5 行，按时间节点拆分。

### 🎥 拍摄建议
- 服装/场景：具体建议
- 道具/文字弹幕：哪些关键词做弹幕叠加
- 表情/动作要点：关键位置的情绪和肢体动作

### 🏷️ 发布建议
- 推荐标题（3 个备选）
- 推荐话题标签（5-8 个）
- 最佳发布时间段
- 封面设计要点

## 核心原则
- 每句话都要有存在的理由，删掉所有废话
- 文案必须是「人话」——就像你真的在对着一个人说话
- 在你的「思考」中可以分析脚本结构，但最终输出的脚本必须干净可直接使用
- 标记 🔥 的地方是情绪高点
"""


# --- 构建用户消息 ---
def build_user_message(
    niche: str,
    topic: str,
    duration: str,
    target_audience: str,
    extra: str,
) -> str:
    """构建发送给 LLM 的用户消息"""
    msg = f"""请为我生成一条短视频脚本：

📌 赛道/领域：{niche}
🎯 具体话题：{topic}
⏱️ 视频时长：{duration}
👥 目标受众：{target_audience}
"""
    if extra:
        msg += f"💡 额外要求：{extra}\n"
    msg += "\n请严格按照系统提示中的格式输出，确保文案完整可直接录制。"
    return msg


# --- 初始化 Session State ---
if "history" not in st.session_state:
    st.session_state.history = []
if "current_script" not in st.session_state:
    st.session_state.current_script = ""
if "generation_count" not in st.session_state:
    st.session_state.generation_count = 0


# --- 侧边栏 ---
with st.sidebar:
    st.markdown("## 🎬 爆款脚本生成器")
    st.markdown("*AI 驱动的短视频脚本创作工具*")
    st.markdown("---")

    # 统计
    col1, col2 = st.columns(2)
    with col1:
        st.markdown(f'<div class="stat-num">{st.session_state.generation_count}</div>', unsafe_allow_html=True)
        st.markdown('<div class="stat-label">已生成脚本</div>', unsafe_allow_html=True)
    with col2:
        st.markdown(f'<div class="stat-num">{len(st.session_state.history)}</div>', unsafe_allow_html=True)
        st.markdown('<div class="stat-label">历史记录</div>', unsafe_allow_html=True)

    st.markdown("---")

    # 生成历史
    st.markdown("### 📚 历史记录")
    if not st.session_state.history:
        st.markdown("*还没有生成过脚本，快去试试吧！*")
    else:
        for i, h in enumerate(reversed(st.session_state.history[-10:])):
            with st.expander(f"{h['style']} · {h['topic'][:20]}...", expanded=False):
                st.markdown(f"**赛道**: {h['niche']}")
                st.markdown(f"**话题**: {h['topic']}")
                st.markdown(f"**风格**: {h['style']}")
                st.markdown(f"**平台**: {h['platform']}")
                st.markdown(f"**时间**: {h['time']}")
                if st.button(f"📋 加载此脚本", key=f"load_{i}"):
                    st.session_state.current_script = h['script']
                    st.rerun()

    st.markdown("---")
    st.markdown("### 🔧 API 设置")
    show_api = st.checkbox("显示 API 配置", value=False)
    if show_api:
        st.code(f"模型: {MODEL}\n接口: {ANTHROPIC_BASE_URL}")
        user_api_key = st.text_input(
            "API Key（填你自己的 Key，留空用默认）",
            type="password",
            help="你的 Key 不会被保存，只在本会话有效"
        )
        if user_api_key:
            st.session_state.user_api_key = user_api_key
        if st.session_state.get("user_api_key"):
            st.success("✅ 正在使用自定义 API Key")

    st.markdown("---")
    st.markdown("*💡 提示：生成结果会自动保存到历史记录，关闭页面不会丢失（本次会话内）。*")


# --- 主界面 ---
st.title("🎬 爆款脚本生成器")
st.markdown("输入你的赛道和话题，AI 帮你生成可直接拍摄的专业短视频脚本")

# --- 输入区 ---
st.markdown("### ⚙️ 配置参数")

# 第一行：平台 + 风格 + 时长
col1, col2, col3 = st.columns(3)
with col1:
    platform = st.selectbox(
        "📱 发布平台",
        ["抖音", "小红书", "B站", "视频号"],
        help="不同平台的脚本节奏和话术不同"
    )
with col2:
    style = st.selectbox(
        "🎭 脚本风格",
        ["干货型", "故事型", "情绪型", "悬念型", "反常识型"],
        help="选择你想要的脚本风格"
    )
with col3:
    duration = st.selectbox(
        "⏱️ 视频时长",
        ["30秒", "60秒（1分钟）", "90秒", "3分钟"],
        index=1,
    )

# 第二行：赛道 + 话题
col1, col2 = st.columns(2)
with col1:
    niche_suggestions = [
        "知识口播", "职场成长", "情感关系", "美妆护肤",
        "美食探店", "穿搭时尚", "健身减脂", "母婴育儿",
        "科技数码", "财经商业", "心理情感", "教育培训",
        "搞笑娱乐", "旅行 Vlog", "家居装修", "其他（自定义）",
    ]
    niche = st.selectbox("🏷️ 赛道/领域", niche_suggestions)
    if niche == "其他（自定义）":
        niche = st.text_input("请输入你的赛道", placeholder="例如：宠物训练、手工皮具...")
with col2:
    topic = st.text_input(
        "🎯 话题/主题",
        placeholder="例如：新人入职第一天如何快速融入团队？",
    )

# 第三行：受众 + 额外要求
col1, col2 = st.columns(2)
with col1:
    target_audience = st.text_input(
        "👥 目标受众",
        placeholder="例如：刚毕业的职场新人、想学化妆的女生...",
    )
with col2:
    extra = st.text_input(
        "💡 额外要求（可选）",
        placeholder="例如：要提到XX产品、开头用提问方式...",
    )

# --- 生成按钮 ---
st.markdown("")
gen_col1, gen_col2, gen_col3 = st.columns([1, 1, 1])
with gen_col2:
    generate_btn = st.button(
        "🚀 生成脚本",
        type="primary",
        use_container_width=True,
        disabled=not topic,
    )

if not topic:
    st.info("👆 请至少填写「话题/主题」后再生成。")

# --- 执行生成 ---
if generate_btn and topic:
    with st.status("🎬 正在为你创作脚本...", expanded=True) as status:
        st.write("📡 分析话题和受众...")
        st.write("✍️ 构建脚本结构...")
        st.write("🎨 润色文案和分镜...")

        try:
            system_prompt = get_system_prompt(style, platform)
            user_message = build_user_message(
                niche=niche,
                topic=topic,
                duration=duration,
                target_audience=target_audience or "通用受众",
                extra=extra,
            )

            result = call_llm(system_prompt, user_message)

            # 保存到历史
            record = {
                "niche": niche,
                "topic": topic,
                "style": style,
                "platform": platform,
                "duration": duration,
                "time": datetime.now().strftime("%H:%M:%S"),
                "script": result,
            }
            st.session_state.history.append(record)
            st.session_state.current_script = result
            st.session_state.generation_count += 1

            status.update(label="✅ 脚本生成完成！", state="complete")
        except Exception as e:
            status.update(label=f"❌ 生成失败", state="error")
            st.error(f"出错了：{str(e)}")


# --- 显示当前脚本 ---
if st.session_state.current_script:
    st.markdown("---")
    st.markdown("### 📝 生成的脚本")

    # 操作按钮行
    col1, col2, col3, col4 = st.columns([1, 1, 1, 3])
    with col1:
        if st.button("📋 复制全文", use_container_width=True):
            # 用 JS 复制到剪贴板
            st.code(st.session_state.current_script, language="markdown")
            st.success("✅ 上方代码块可选中复制（Ctrl+C）")
    with col2:
        # 下载为 Markdown
        st.download_button(
            label="💾 下载 .md",
            data=st.session_state.current_script,
            file_name=f"脚本_{topic[:20]}_{datetime.now().strftime('%H%M')}.md",
            mime="text/markdown",
            use_container_width=True,
        )
    with col3:
        if st.button("🔄 重新生成", use_container_width=True):
            st.session_state.current_script = ""
            st.rerun()

    # 渲染脚本
    st.markdown(st.session_state.current_script)

else:
    # 没有脚本时显示占位
    st.markdown("---")
    st.markdown("""
    <div style="text-align:center; padding:60px 20px; color:#666;">
        <div style="font-size:4em; margin-bottom:16px;">🎬</div>
        <div style="font-size:1.2em; margin-bottom:8px;">填写参数，点击「生成脚本」</div>
        <div style="font-size:0.9em;">AI 会为你生成包含分镜、文案、BGM 的完整拍摄脚本</div>
    </div>
    """, unsafe_allow_html=True)


# --- 底部 ---
st.markdown("---")
st.markdown(
    "<div style='text-align:center; color:#555; font-size:0.8em;'>"
    "🎬 爆款脚本生成器 · Powered by DeepSeek · 脚本仅供参考，请根据实际情况调整"
    "</div>",
    unsafe_allow_html=True,
)
