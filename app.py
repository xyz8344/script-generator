"""
🎬 爆款脚本生成器 — AI 驱动的短视频脚本创作工具
输入赛道 + 话题，一键生成可直接拍摄的专业脚本
支持自动采集最新爆款案例，持续进化
"""
import streamlit as st
import requests
import re
import os
import json
import time
from datetime import datetime
from dotenv import load_dotenv
import knowledge_db as db
import collector

# --- 加载配置（优先级：Streamlit Secrets > 环境变量 > .env > 默认值）---
load_dotenv()

# 赛道列表（模块级常量，多处共用）
NICHE_SUGGESTIONS = [
    "知识口播", "职场成长", "情感关系", "美妆护肤",
    "美食探店", "穿搭时尚", "健身减脂", "母婴育儿",
    "科技数码", "财经商业", "心理情感", "教育培训",
    "搞笑娱乐", "旅行Vlog", "家居装修", "其他（自定义）",
]

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

# --- CSS ---
st.markdown("""
<style>
    #MainMenu {display: none;}
    footer {visibility: hidden;}

    .script-card {
        background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%);
        border: 1px solid #2a2a4a;
        border-radius: 12px;
        padding: 24px;
        margin: 12px 0;
    }

    .hook-box {
        background: linear-gradient(135deg, #FF6B35 0%, #FF8F65 100%);
        color: white;
        padding: 16px 20px;
        border-radius: 8px;
        font-size: 1.1em;
        font-weight: 600;
        margin: 12px 0;
    }

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

    .case-item {
        background: #1a1a2e;
        border: 1px solid #2a2a4a;
        border-radius: 10px;
        padding: 16px;
        margin: 8px 0;
        transition: border-color 0.2s;
    }
    .case-item:hover {
        border-color: #FF6B35;
    }

    .badge {
        display: inline-block;
        padding: 2px 8px;
        border-radius: 10px;
        font-size: 0.72em;
        font-weight: 600;
    }
    .badge-hot { background: #3a1a1a; color: #FF6B35; }
    .badge-auto { background: #1a2a3a; color: #7dcfff; }
    .badge-manual { background: #1a3a2a; color: #7dcea0; }
</style>
""", unsafe_allow_html=True)


# --- LLM 调用 ---
def _fetch_page_title(url: str) -> str:
    """尝试从网页抓取标题（og:title 或 <title>），用于抖音/小红书等平台的链接"""
    try:
        resp = requests.get(
            url,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "Accept": "text/html,application/xhtml+xml",
                "Accept-Language": "zh-CN,zh;q=0.9",
            },
            timeout=8,
            allow_redirects=True,
        )
        html = resp.text[:50000]  # 只读前 50KB
        # 优先 og:title
        og_match = re.search(r'<meta[^>]+property=["\']og:title["\'][^>]+content=["\']([^"\']+)["\']', html, re.IGNORECASE)
        if og_match:
            return og_match.group(1).strip()
        # 退而求其次：<title>
        title_match = re.search(r'<title[^>]*>(.+?)</title>', html, re.IGNORECASE)
        if title_match:
            return title_match.group(1).strip()
    except Exception:
        pass
    return ""


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
def get_system_prompt(style: str, platform: str, niche: str = "") -> str:
    """根据风格和平台生成系统提示词（含爆款案例参考）"""

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

    # 📚 搜索相关爆款案例
    case_reference = ""
    if niche:
        refs = db.search(niche, niche=niche, limit=3)
        if refs:
            case_reference = "\n\n## 📚 最近爆款案例参考\n参考以下案例的风格和结构（但不要照抄内容）：\n\n"
            case_reference += db.format_for_prompt(refs, max_cases=3)

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
{case_reference}

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
- 标记 🔥 的地方是情绪高点
"""


def build_user_message(niche, topic, duration, target_audience, extra):
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
for key, default in [
    ("history", []),
    ("current_script", ""),
    ("generation_count", 0),
    ("page", "🎬 脚本生成"),
]:
    if key not in st.session_state:
        st.session_state[key] = default


# ===================== 侧边栏 =====================
with st.sidebar:
    st.markdown("## 🎬 爆款脚本生成器")
    st.markdown("*AI 驱动的短视频脚本创作工具*")
    st.markdown("---")

    # 页面导航
    page = st.radio(
        "📋 导航",
        ["🎬 脚本生成", "📚 知识库管理"],
        key="page",
    )

    st.markdown("---")

    # 统计
    col1, col2 = st.columns(2)
    with col1:
        st.markdown(f'<div class="stat-num">{st.session_state.generation_count}</div>', unsafe_allow_html=True)
        st.markdown('<div class="stat-label">已生成脚本</div>', unsafe_allow_html=True)
    with col2:
        kb_count = db.count()
        st.markdown(f'<div class="stat-num">{kb_count["total"]}</div>', unsafe_allow_html=True)
        st.markdown('<div class="stat-label">知识库案例</div>', unsafe_allow_html=True)

    st.markdown("---")

    # API 设置
    st.markdown("### 🔧 API 设置")
    show_api = st.checkbox("显示配置", value=False)
    if show_api:
        st.code(f"模型: {MODEL}\n接口: {ANTHROPIC_BASE_URL}")
        user_api_key = st.text_input(
            "自定义 API Key（留空用默认）",
            type="password",
        )
        if user_api_key:
            st.session_state.user_api_key = user_api_key
            st.success("✅ 已使用自定义 Key")


# ===================== 页面1：脚本生成 =====================
if page == "🎬 脚本生成":
    st.title("🎬 爆款脚本生成器")
    st.markdown("输入你的赛道和话题，AI 参考最新爆款案例为你生成专业脚本")

    # 输入区
    st.markdown("### ⚙️ 配置参数")

    col1, col2, col3 = st.columns(3)
    with col1:
        platform = st.selectbox(
            "📱 发布平台",
            ["抖音", "小红书", "B站", "视频号"],
        )
    with col2:
        style = st.selectbox(
            "🎭 脚本风格",
            ["干货型", "故事型", "情绪型", "悬念型", "反常识型"],
        )
    with col3:
        duration = st.selectbox(
            "⏱️ 视频时长",
            ["30秒", "60秒（1分钟）", "90秒", "3分钟"],
            index=1,
        )

    col1, col2 = st.columns(2)
    with col1:
        niche = st.selectbox("🏷️ 赛道/领域", NICHE_SUGGESTIONS)
        if niche == "其他（自定义）":
            niche = st.text_input("请输入赛道", placeholder="例如：宠物训练、手工皮具...")
    with col2:
        topic = st.text_input(
            "🎯 话题/主题",
            placeholder="例如：新人入职第一天如何快速融入团队？",
        )

    col1, col2 = st.columns(2)
    with col1:
        target_audience = st.text_input(
            "👥 目标受众",
            placeholder="例如：刚毕业的职场新人...",
        )
    with col2:
        extra = st.text_input(
            "💡 额外要求（可选）",
            placeholder="例如：开头用提问、提到XX产品...",
        )

    # 搜索案例数量提示
    if niche and niche != "其他（自定义）":
        refs = db.search(niche, niche=niche, limit=10)
        if refs:
            st.info(f"📚 知识库中有 **{len(refs)}** 条「{niche}」相关爆款案例可供参考")
        else:
            st.warning(f"⚠️ 知识库中暂无「{niche}」的案例，建议先去「📚 知识库管理」更新案例库")

    # 生成按钮
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

    if generate_btn and topic:
        with st.status("🎬 正在为你创作脚本...", expanded=True) as status:
            st.write("📡 分析话题和受众...")
            st.write("📚 检索相关爆款案例...")
            st.write("✍️ 构建脚本结构...")
            st.write("🎨 润色文案和分镜...")

            try:
                system_prompt = get_system_prompt(style, platform, niche=niche)
                user_message = build_user_message(
                    niche=niche, topic=topic, duration=duration,
                    target_audience=target_audience or "通用受众", extra=extra,
                )
                result = call_llm(system_prompt, user_message)

                st.session_state.history.append({
                    "niche": niche, "topic": topic, "style": style,
                    "platform": platform, "duration": duration,
                    "time": datetime.now().strftime("%H:%M:%S"), "script": result,
                })
                st.session_state.current_script = result
                st.session_state.generation_count += 1

                status.update(label="✅ 脚本生成完成！", state="complete")
            except Exception as e:
                status.update(label="❌ 生成失败", state="error")
                st.error(f"出错了：{str(e)}")

    # 显示当前脚本
    if st.session_state.current_script:
        st.markdown("---")
        st.markdown("### 📝 生成的脚本")

        col1, col2, col3, col4 = st.columns([1, 1, 1, 3])
        with col1:
            st.download_button(
                label="💾 下载 .md",
                data=st.session_state.current_script,
                file_name=f"脚本_{datetime.now().strftime('%m%d_%H%M')}.md",
                mime="text/markdown",
                use_container_width=True,
            )
        with col2:
            if st.button("🔄 重新生成", use_container_width=True):
                st.session_state.current_script = ""
                st.rerun()

        st.markdown(st.session_state.current_script)

    else:
        st.markdown("---")
        st.markdown("""
        <div style="text-align:center; padding:60px 20px; color:#666;">
            <div style="font-size:4em; margin-bottom:16px;">🎬</div>
            <div style="font-size:1.2em; margin-bottom:8px;">填写参数，点击「生成脚本」</div>
            <div style="font-size:0.9em;">AI 会参考最新爆款案例为你生成完整拍摄脚本</div>
        </div>
        """, unsafe_allow_html=True)


# ===================== 页面2：知识库管理 =====================
elif page == "📚 知识库管理":
    st.title("📚 知识库管理")
    st.markdown("管理爆款案例库——让 AI 持续学习最新爆款模式")

    # ---- Tab：自动采集 ----
    tab1, tab2, tab3 = st.tabs(["🔄 自动更新", "📋 案例浏览", "✍️ 手动录入"])

    # === 自动更新 Tab ===
    with tab1:
        st.markdown("### 🔄 一键更新案例库")

        # ===== 平台选择 =====
        platform_choice = st.radio(
            "📱 内容平台",
            ["B站", "抖音", "小红书"],
            horizontal=True,
            help="B站支持自动搜索 + 热门榜，抖音/小红书需手动粘贴链接"
        )

        # ========== B站模式：全自动采集 ==========
        if platform_choice == "B站":
            st.markdown("系统会自动搜索 B站热门视频，筛选爆款，AI 拆解脚本结构后入库。")

            # 时间范围
            time_options = [("7天内", 7), ("14天内", 14), ("30天内", 30), ("不限", 0)]
            max_age_days = st.selectbox(
                "📅 发布时间范围",
                time_options,
                format_func=lambda x: x[0],
                index=0,
                help="只收录指定天数内发布的视频"
            )[1]

            # 采集设置
            st.markdown("#### ⚙️ 采集设置")
            col1, col2, col3 = st.columns(3)
            with col1:
                collect_niche = st.selectbox(
                    "🎯 目标赛道",
                    ["知识口播", "职场成长", "情感关系", "美妆护肤",
                     "美食探店", "穿搭时尚", "健身减脂", "科技数码",
                     "财经商业", "搞笑娱乐", "旅行Vlog", "家居装修"],
                    key="collect_niche",
                    help="选择要搜索的赛道，系统会使用对应关键词搜索"
                )
            with col2:
                threshold = st.number_input(
                    "🔥 爆款点赞阈值",
                    min_value=1000,
                    max_value=1000000,
                    value=10000,
                    step=1000,
                    help="点赞数超过这个值才算是爆款，会被收录"
                )
            with col3:
                max_collect = st.slider(
                    "📊 最多采集条数",
                    min_value=5,
                    max_value=30,
                    value=10,
                    help="一次最多采集多少条视频"
                )

            # 采集方式
            collect_method = st.radio(
                "📡 采集来源",
                ["🔍 关键词搜索（精准但量少）", "🔥 热门榜单（量大但不够精准）"],
                horizontal=True,
            )

            # 自定义关键词（仅搜索模式）
            custom_keyword = ""
            if "关键词" in collect_method:
                custom_keyword = st.text_input(
                    "🔑 自定义搜索关键词（留空则自动根据赛道匹配）",
                    placeholder="例如：AI 工具 效率提升",
                    key="custom_keyword",
                )

            # 更新按钮
            st.markdown("")
            col1, col2, col3 = st.columns([1, 2, 1])
            with col2:
                update_btn = st.button(
                    "🔄 开始更新案例库",
                    type="primary",
                    use_container_width=True,
                )

            if update_btn:
                use_popular = "热门" in collect_method
                progress = st.progress(0, text="准备中...")

                with st.status("🔄 正在采集...", expanded=True) as status:
                    try:
                        progress.progress(10, text="🔍 搜索热门视频...")

                        result = collector.collect_and_store(
                            niche=collect_niche,
                            llm_call=call_llm,
                            threshold_likes=threshold,
                            max_videos=max_collect,
                            use_popular=use_popular,
                            custom_keyword=custom_keyword,
                            max_age_days=max_age_days,
                        )

                        progress.progress(90, text="📝 处理完成...")

                        st.success(f"✅ {result['message']}")
                        if "message" in result and result.get("videos"):
                            pass  # 有结果，下面展示

                        # 展示新增的案例
                        if result.get("videos"):
                            st.markdown("#### 📝 本次新增案例")
                            for v in result["videos"]:
                                pubdate_info = f" · 📅 {v.get('pubdate_str', '')}" if v.get('pubdate_str') else ""
                                with st.expander(f"🔥 {v['title'][:60]}... （{v['likes']} 赞{pubdate_info}）"):
                                    st.markdown(f"**链接**: {v['url']}")
                                    st.markdown(f"**数据**: {v['views']} 播放 · {v['likes']} 点赞 · {v['comments']} 评论")
                                    st.markdown(f"**作者**: {v['author']}")
                                    st.markdown("**拆解分析**:")
                                    st.markdown(v.get('script_analysis', '无'))

                        progress.progress(100, text="✅ 完成！")
                        status.update(label=f"✅ 更新完成 — {result['message']}", state="complete")

                    except Exception as e:
                        status.update(label="❌ 更新失败", state="error")
                        st.error(f"出错了：{str(e)}")

        # ========== 抖音 / 小红书：半自动链接录入 ==========
        else:
            st.info(
                f"💡 **{platform_choice}** 没有公开的内容搜索 API，无法像 B站 一样自动搜索热门视频。\n\n"
                "但你可以粘贴目标视频的分享链接，系统会自动抓取标题并调用 AI 拆解脚本结构入库。\n\n"
                "📌 **提示**：也可以切换到右侧的「✍️ 一键录入」标签，粘贴单个链接进行完整分析。"
            )

            st.markdown("#### ⚙️ 采集设置")
            col1, col2 = st.columns(2)
            with col1:
                manual_niche = st.selectbox(
                    "🎯 目标赛道",
                    ["知识口播", "职场成长", "情感关系", "美妆护肤",
                     "美食探店", "穿搭时尚", "健身减脂", "科技数码",
                     "财经商业", "搞笑娱乐", "旅行Vlog", "家居装修"],
                    key="manual_collect_niche",
                )
            with col2:
                manual_threshold = st.number_input(
                    "🔥 爆款点赞参考值",
                    min_value=1000,
                    max_value=1000000,
                    value=10000,
                    step=1000,
                    help="抖音/小红书无法自动获取真实点赞数，此值仅作记录参考",
                    key="manual_threshold",
                )

            st.markdown("#### 🔗 视频链接（每行一个）")
            urls_text = st.text_area(
                "粘贴视频分享链接",
                placeholder="https://www.douyin.com/video/xxxxx\nhttps://www.xiaohongshu.com/explore/xxxxx",
                height=150,
                key="manual_urls_batch",
            )

            # 链接预览（尝试抓取标题）
            if urls_text.strip():
                urls = [u.strip() for u in urls_text.split("\n") if u.strip()]
                st.markdown(f"📊 共解析到 **{len(urls)}** 个链接")
                with st.expander("📡 标题预览（自动抓取）", expanded=len(urls) <= 3):
                    for i, url in enumerate(urls[:10]):
                        title = _fetch_page_title(url)
                        if title:
                            st.caption(f"{i+1}. ✅ {title[:80]}")
                        else:
                            st.caption(f"{i+1}. ⚠️ 无法获取标题，将使用链接作为标识")

            # 分析按钮
            st.markdown("")
            col1, col2, col3 = st.columns([1, 2, 1])
            with col2:
                manual_btn = st.button(
                    "🔍 分析并入库",
                    type="primary",
                    use_container_width=True,
                    disabled=not urls_text.strip(),
                    key="manual_collect_btn",
                )

            if manual_btn and urls_text.strip():
                urls = [u.strip() for u in urls_text.split("\n") if u.strip()]
                progress = st.progress(0, text="准备中...")
                added, failed = 0, 0

                with st.status(f"🔄 正在处理 {len(urls)} 个链接...", expanded=True) as status:
                    for i, url in enumerate(urls):
                        progress.progress(
                            int((i + 1) / len(urls) * 100),
                            text=f"处理中 ({i+1}/{len(urls)})..."
                        )

                        # 检查去重
                        existing = db.get_all(500)
                        if url in {c.get("url", "") for c in existing}:
                            st.caption(f"⏭️ [{i+1}] 已存在，跳过：{url[:60]}...")
                            continue

                        # 1. 抓取标题
                        title = _fetch_page_title(url)
                        if not title:
                            title = url.rstrip("/").split("/")[-1][:50] or f"未命名视频_{i+1}"

                        # 2. 构建 video_info
                        video_info = {
                            "title": title,
                            "url": url,
                            "description": "",
                            "tags": [],
                            "views": "?",
                            "likes": f"{manual_threshold}+" if manual_threshold else "?",
                            "comments": "?",
                            "likes_raw": 0,
                            "duration": "",
                            "author": "",
                            "platform": platform_choice,
                        }

                        # 3. AI 拆解
                        try:
                            analysis = collector.analyze_script_structure(video_info, call_llm)
                            # 4. 入库
                            case = {
                                "title": title,
                                "url": url,
                                "platform": platform_choice,
                                "niche": manual_niche,
                                "views": "?",
                                "likes": f"{manual_threshold}+",
                                "comments": "?",
                                "duration": "",
                                "author": "",
                                "description": "",
                                "tags": [],
                                "script_analysis": analysis,
                                "source": "半自动采集",
                                "pubdate": 0,
                                "pubdate_str": "",
                            }
                            db.add_case(case)
                            added += 1
                            st.caption(f"✅ [{i+1}] 已入库：{title[:50]}...")
                            time.sleep(0.5)  # LLM 限速
                        except Exception as e:
                            failed += 1
                            st.warning(f"❌ [{i+1}] 处理失败：{str(e)[:100]}")

                    progress.progress(100, text="✅ 完成！")
                    if added > 0:
                        st.success(f"✅ 成功入库 {added} 条案例（赛道：{manual_niche}）")
                    if failed > 0:
                        st.warning(f"⚠️ {failed} 条处理失败")
                    status.update(
                        label=f"✅ 完成 — 新增 {added} 条，失败 {failed} 条",
                        state="complete"
                    )

    # === 案例浏览 Tab ===
    with tab2:
        st.markdown("### 📋 案例列表")

        stats = db.count()
        col1, col2, col3 = st.columns(3)
        with col1:
            st.metric("📦 总案例数", stats["total"])
        with col2:
            st.metric("🏷️ 覆盖赛道", len(stats["by_niche"]))
        with col3:
            st.metric("🕐 最后更新", stats["last_updated"])

        # 赛道分布
        if stats["by_niche"]:
            st.markdown("#### 赛道分布")
            niche_cols = st.columns(4)
            for i, (n, c) in enumerate(sorted(stats["by_niche"].items(), key=lambda x: -x[1])):
                with niche_cols[i % 4]:
                    st.markdown(f"- **{n}**: {c} 条")

        st.markdown("---")

        # 案例列表
        all_cases = db.get_all(100)
        if not all_cases:
            st.info("知识库为空，去「🔄 自动更新」或「✍️ 手动录入」添加案例吧！")
        else:
            # 筛选
            filter_niche = st.selectbox(
                "筛选赛道",
                ["全部"] + list(stats["by_niche"].keys()),
                key="filter_niche",
            )
            search_kw = st.text_input("关键词搜索", placeholder="输入关键词过滤...")

            filtered = all_cases
            if filter_niche != "全部":
                filtered = [c for c in filtered if c.get("niche") == filter_niche]
            if search_kw:
                filtered = db.search(search_kw, limit=50)

            st.markdown(f"共 **{len(filtered)}** 条案例")
            st.markdown("---")

            for c in filtered[:20]:
                source_badge = '<span class="badge badge-auto">🤖 自动采集</span>' if c.get("source") == "自动采集" else '<span class="badge badge-manual">✍️ 手动录入</span>'
                st.markdown(f"""
<div class="case-item">
    <div style="display:flex;justify-content:space-between;align-items:start;">
        <div style="flex:1;">
            <strong>🔥 {c.get('title', '无标题')[:80]}</strong>
            <div style="margin:4px 0;font-size:0.85em;color:#888;">
                {c.get('platform', '?')} · {c.get('niche', '?')} ·
                {c.get('views', '?')} 播放 · {c.get('likes', '?')} 赞 ·
                {source_badge}
            </div>
        </div>
    </div>
</div>""", unsafe_allow_html=True)

                # 展开拆解内容
                with st.expander(f"查看拆解 — {c.get('title', '')[:50]}..."):
                    st.markdown(c.get('script_analysis', '暂无拆解'))
                    st.markdown(f"[🔗 原视频链接]({c.get('url', '#')})")
                    if st.button("🗑️ 删除此案例", key=f"del_{c['id']}"):
                        db.delete_case(c["id"])
                        st.success("已删除")
                        st.rerun()

    # === 手动录入 Tab ===
    with tab3:
        st.markdown("### ✍️ 一键录入")
        st.markdown("粘贴 B站/抖音/小红书 视频链接，系统自动获取信息 + AI 拆解脚本，无需手动填写。")

        # ===== 一键链接录入 =====
        quick_url = st.text_input(
            "🔗 视频链接",
            placeholder="粘贴视频链接，例如 https://www.bilibili.com/video/BV1xx411c7mD",
            key="quick_url",
        )

        # 自动识别平台
        platform_detected = "未知"
        if quick_url:
            if "bilibili" in quick_url:
                platform_detected = "B站"
            elif "douyin" in quick_url or "v.douyin" in quick_url:
                platform_detected = "抖音"
            elif "xiaohongshu" in quick_url or "xhslink" in quick_url:
                platform_detected = "小红书"
            elif "weishi" in quick_url:
                platform_detected = "视频号"

        # 非 B站 链接：需要用户输入标题（或自动抓取）
        auto_title = ""
        if quick_url and platform_detected not in ("B站", "未知"):
            # 尝试从页面抓取标题
            auto_title = _fetch_page_title(quick_url)
            if auto_title:
                st.caption(f"📡 自动获取标题：**{auto_title[:60]}**")

        # 非 B站 链接显示标题输入框
        quick_title = ""
        if quick_url and platform_detected not in ("B站", "未知"):
            quick_title = st.text_input(
                "📝 视频标题（必填）",
                value=auto_title,
                placeholder="输入视频标题，例如：3个让你变强的AI工具...",
                key="quick_title",
            )

        is_bilibili = "bilibili" in quick_url and "BV" in quick_url
        can_analyze = bool(quick_url) and (is_bilibili or bool(quick_title.strip()))

        col1, col2 = st.columns([1, 3])
        with col1:
            analyze_btn = st.button(
                "🔍 一键分析",
                type="primary",
                use_container_width=True,
                disabled=not can_analyze,
            )
        with col2:
            if quick_url and not can_analyze:
                if not is_bilibili and not quick_title.strip():
                    st.caption("⚠️ 抖音/小红书链接需要手动输入视频标题")

        if analyze_btn and quick_url and can_analyze:
            with st.status("🔄 处理中...", expanded=True) as status:
                bvid = None
                video_info = None

                # B站链接：自动获取视频信息
                if is_bilibili:
                    st.write("📡 正在从 B站 获取视频信息...")
                    match = re.search(r'BV[a-zA-Z0-9]+', quick_url)
                    if match:
                        bvid = match.group()
                        enriched = collector._enrich_video_stats(bvid)
                        if enriched:
                            # 再获取标题、作者、描述等
                            try:
                                resp = requests.get(
                                    "https://api.bilibili.com/x/web-interface/view",
                                    params={"bvid": bvid},
                                    headers=collector.BILIBILI_HEADERS,
                                    timeout=10,
                                )
                                data = resp.json()
                                if data.get("code") == 0:
                                    d = data["data"]
                                    video_info = {
                                        "title": d.get("title", ""),
                                        "url": quick_url,
                                        "description": d.get("desc", ""),
                                        "tags": d.get("tagname", "").split(",") if d.get("tagname") else [],
                                        "views": collector._fmt_num(enriched.get("views_raw", 0)),
                                        "likes": collector._fmt_num(enriched.get("likes_raw", 0)),
                                        "comments": collector._fmt_num(enriched.get("comments_raw", 0)),
                                        "likes_raw": enriched.get("likes_raw", 0),
                                        "duration": f"{d.get('duration', 0) // 60}:{d.get('duration', 0) % 60:02d}",
                                        "author": d.get("owner", {}).get("name", ""),
                                        "platform": "B站",
                                        "bvid": bvid,
                                    }
                                    st.write(f"✅ 已获取：**{video_info['title'][:50]}...**")
                                    st.write(f"📊 {video_info['views']} 播放 · {video_info['likes']} 点赞")
                            except Exception:
                                pass
                else:
                    # 非 B站 链接：使用用户输入的标题
                    video_info = {
                        "title": quick_title.strip(),
                        "url": quick_url,
                        "description": "",
                        "tags": [],
                        "views": "?",
                        "likes": "?",
                        "comments": "?",
                        "likes_raw": 0,
                        "duration": "",
                        "author": "",
                        "platform": platform_detected,
                    }
                    st.write(f"📡 平台：**{platform_detected}**，将基于标题 + 链接进行分析")

                # B站获取失败的回退
                if not video_info:
                    video_info = {
                        "title": quick_url.split("/")[-1][:50] if quick_url else "未命名视频",
                        "url": quick_url,
                        "description": "",
                        "tags": [],
                        "views": "?",
                        "likes": "?",
                        "comments": "?",
                        "likes_raw": 0,
                        "duration": "",
                        "author": "",
                        "platform": platform_detected if platform_detected != "未知" else "B站",
                    }
                    st.write("⚠️ 无法自动获取信息，将基于链接进行分析")

                # AI 拆解
                st.write("🧠 AI 拆解脚本结构中...")
                analysis = collector.analyze_script_structure(video_info, call_llm)

                # 自动推断赛道
                inferred_niche = "其他"
                title_tags = video_info.get("title", "") + " " + " ".join(video_info.get("tags", []))
                for niche in ["知识口播", "职场成长", "情感关系", "美妆护肤", "美食探店",
                              "穿搭时尚", "健身减脂", "母婴育儿", "科技数码", "财经商业",
                              "搞笑娱乐", "旅行Vlog", "家居装修"]:
                    if niche[:2] in title_tags:
                        inferred_niche = niche
                        break

                # 入库
                case = {
                    "title": video_info["title"],
                    "url": video_info["url"],
                    "platform": video_info["platform"],
                    "niche": inferred_niche,
                    "views": video_info.get("views", "?"),
                    "likes": video_info.get("likes", "?"),
                    "comments": video_info.get("comments", "?"),
                    "duration": video_info.get("duration", ""),
                    "author": video_info.get("author", ""),
                    "description": video_info.get("description", "")[:500],
                    "tags": video_info.get("tags", []),
                    "script_analysis": analysis,
                    "source": "一键录入",
                }
                db.add_case(case)

                status.update(label="✅ 分析完成！", state="complete")
                st.success(f"✅ 已入库：**{video_info['title'][:50]}...**")
                st.markdown("---")
                st.markdown("#### 📝 拆解结果")
                st.markdown(analysis)
                st.info(f"🏷️ 自动归类赛道：**{inferred_niche}**")

        st.markdown("---")

        # ===== 高级：手动/批量录入（折叠） =====
        with st.expander("📝 高级：手动详细录入 / 批量录入", expanded=False):
            st.markdown("适用于非 B站 链接，或需要自定义字段的场景。")

            col1, col2 = st.columns(2)
            with col1:
                manual_title = st.text_input("视频标题 *", placeholder="粘贴视频标题...", key="manual_title")
                manual_url = st.text_input("视频链接", placeholder="https://...", key="manual_url")
                manual_niche = st.selectbox("所属赛道", NICHE_SUGGESTIONS, key="manual_niche")
                manual_platform = st.selectbox("平台", ["抖音", "小红书", "B站", "视频号"], key="manual_platform")
            with col2:
                manual_text = st.text_area(
                    "视频文案/字幕内容（可选，越完整拆解越精准）",
                    placeholder="如果有视频字幕或文案，粘贴到这里。",
                    height=150,
                    key="manual_text",
                )
                manual_likes = st.text_input("点赞数", placeholder="例如：5.2万", key="manual_likes")

            if st.button("📝 录入详细案例", type="primary", disabled=not manual_title):
                with st.spinner("AI 拆解中..."):
                    fake_video = {
                        "title": manual_title,
                        "url": manual_url,
                        "description": manual_text[:500] if manual_text else "",
                        "tags": [],
                        "views": "?",
                        "likes": manual_likes or "?",
                        "comments": "?",
                        "duration": "",
                        "author": "",
                        "platform": manual_platform,
                    }
                    analysis = collector.analyze_script_structure(fake_video, call_llm)
                    db.add_case({
                        "title": manual_title,
                        "url": manual_url,
                        "platform": manual_platform,
                        "niche": manual_niche,
                        "views": "?",
                        "likes": manual_likes or "?",
                        "comments": "?",
                        "description": manual_text[:500] if manual_text else "",
                        "tags": [],
                        "script_analysis": analysis,
                        "source": "手动录入",
                    })
                    st.success(f"✅ 已入库：{manual_title[:40]}...")
                    st.rerun()

            st.markdown("---")
            st.markdown("#### ⚡ 批量快速录入（仅标题）")

            quick_titles = st.text_area(
                "每行一个视频标题",
                placeholder="新人入职第一天千万别做这三件事\n面试官最讨厌的5个回答\n35岁被裁后才明白的真相",
                height=120,
                key="quick_titles",
            )
            quick_niche = st.selectbox("统一赛道", NICHE_SUGGESTIONS, key="quick_niche")

            if st.button("⚡ 批量快速录入", disabled=not quick_titles):
                titles = [t.strip() for t in quick_titles.split("\n") if t.strip()]
                added = 0
                progress = st.progress(0)
                for i, title in enumerate(titles):
                    with st.spinner(f"拆解中 ({i+1}/{len(titles)})：{title[:30]}..."):
                        fake_video = {
                            "title": title, "url": "", "description": "",
                            "tags": [], "views": "?", "likes": "?", "comments": "?",
                            "duration": "", "author": "", "platform": "未知",
                        }
                        analysis = collector.analyze_script_structure(fake_video, call_llm)
                        db.add_case({
                            "title": title,
                            "url": "",
                            "platform": "未知",
                            "niche": quick_niche,
                            "views": "?", "likes": "?", "comments": "?",
                            "description": "", "tags": [],
                            "script_analysis": analysis,
                            "source": "手动录入",
                        })
                        added += 1
                        time.sleep(0.5)
                    progress.progress((i + 1) / len(titles))
                st.success(f"✅ 批量录入完成！新增 {added} 条案例")

# --- 底部 ---
st.markdown("---")
st.markdown(
    "<div style='text-align:center; color:#555; font-size:0.8em;'>"
    "🎬 爆款脚本生成器 · Powered by DeepSeek · 知识库越用越聪明"
    "</div>",
    unsafe_allow_html=True,
)
