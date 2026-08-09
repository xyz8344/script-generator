"""
采集器模块 — 自动抓取B站热门视频并拆解脚本结构
"""
import requests
import time
from datetime import datetime
from typing import Optional
import knowledge_db as db


# --- B站 API ---
BILIBILI_SEARCH = "https://api.bilibili.com/x/web-interface/search/type"
BILIBILI_POPULAR = "https://api.bilibili.com/x/web-interface/popular"
BILIBILI_VIDEO_INFO = "https://api.bilibili.com/x/web-interface/view"
BILIBILI_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Referer": "https://www.bilibili.com",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "zh-CN,zh;q=0.9",
    "Cookie": "buvid3=auto; buvid4=auto; buvid_fp=auto",  # 基础标识，降低风控概率
}

# 赛道 → B站搜索关键词映射
NICHE_KEYWORDS = {
    "知识口播": "知识分享 干货",
    "职场成长": "职场 打工人",
    "情感关系": "情感 恋爱 婚姻",
    "美妆护肤": "美妆 化妆教程",
    "美食探店": "美食探店 探店打卡",
    "穿搭时尚": "穿搭 时尚",
    "健身减脂": "健身 减肥 减脂",
    "母婴育儿": "带娃 育儿",
    "科技数码": "数码 手机 电脑",
    "财经商业": "商业 创业 搞钱",
    "搞笑娱乐": "搞笑 段子",
    "旅行Vlog": "旅行 vlog",
    "家居装修": "装修 家居",
}


def search_videos(keyword: str, limit: int = 20) -> list[dict]:
    """搜索B站视频"""
    params = {
        "search_type": "video",
        "keyword": keyword,
        "order": "click",  # 按播放量排序
        "duration": 4,     # 10分钟以内
        "page": 1,
    }
    try:
        resp = requests.get(
            BILIBILI_SEARCH, params=params,
            headers=BILIBILI_HEADERS, timeout=15
        )
        if _is_blocked(resp):
            print("[collector] 搜索被B站风控拦截，返回了验证页面")
            return []
        data = resp.json()
        if data.get("code") != 0:
            print(f"[collector] 搜索API返回错误: code={data.get('code')}, message={data.get('message', '')}")
            return []

        videos = []
        for item in data.get("data", {}).get("result", [])[:limit]:
            bvid = item.get("bvid", "")
            play = item.get("play", 0)
            favorites = item.get("favorites", 0)
            review = item.get("review", 0)

            videos.append({
                "bvid": bvid,
                "title": item.get("title", "").replace('<em class="keyword">', '').replace('</em>', ''),
                "description": item.get("description", ""),
                "tags": item.get("tag", "").split(",") if item.get("tag") else [],
                "views_raw": play,
                "likes_raw": favorites,   # 搜索接口无点赞字段，先用收藏数；后续在 collect_and_store 中通过详情API补充
                "comments_raw": review,
                "views": _fmt_num(play),
                "likes": _fmt_num(favorites),
                "comments": _fmt_num(review),
                "duration": item.get("duration", ""),
                "author": item.get("author", ""),
                "url": f"https://www.bilibili.com/video/{bvid}",
                "platform": "B站",
            })
        return videos
    except Exception as e:
        print(f"[collector] 搜索失败: {e}")
        return []


def get_popular_videos(pn: int = 1, ps: int = 30) -> list[dict]:
    """获取B站热门视频"""
    params = {"pn": pn, "ps": ps}
    try:
        resp = requests.get(
            BILIBILI_POPULAR, params=params,
            headers=BILIBILI_HEADERS, timeout=15
        )
        if _is_blocked(resp):
            print("[collector] 热门列表被B站风控拦截")
            return []
        data = resp.json()
        if data.get("code") != 0:
            return []

        videos = []
        for item in data.get("data", {}).get("list", []):
            stat = item.get("stat", {})
            view = stat.get("view", 0)
            like = stat.get("like", 0)
            reply = stat.get("reply", 0)
            videos.append({
                "bvid": item.get("bvid", ""),
                "title": item.get("title", ""),
                "description": item.get("desc", ""),
                "tags": [],  # 热门接口没有标签
                "views_raw": view,
                "likes_raw": like,
                "comments_raw": reply,
                "views": _fmt_num(view),
                "likes": _fmt_num(like),
                "comments": _fmt_num(reply),
                "duration": item.get("duration", ""),
                "author": item.get("owner", {}).get("name", ""),
                "url": f"https://www.bilibili.com/video/{item.get('bvid', '')}",
                "platform": "B站",
            })
        return videos
    except Exception as e:
        print(f"[collector] 热门获取失败: {e}")
        return []


def analyze_script_structure(video: dict, llm_call) -> str:
    """调用 LLM 拆解视频的脚本结构"""
    prompt = f"""你是一个短视频脚本分析专家。请根据以下视频信息，**逆向推断**这条视频的脚本结构和爆款要素。

视频标题：{video['title']}
视频简介：{video['description']}
作者：{video['author']}
播放量：{video['views']} · 点赞：{video['likes']} · 评论：{video['comments']}
标签：{', '.join(video.get('tags', []))}
时长：{video.get('duration', '未知')}

请用 5-8 句话分析：
1. 这条视频的脚本结构（钩子 → 展开 → 高潮 → 结尾）
2. 它为什么能成为爆款（从标题/选题/情绪节奏分析）
3. 开头可能用了什么钩子技巧
4. 可以复用的模板是什么

输出要简洁，每条分析控制在 2-3 行以内。"""

    try:
        result = llm_call(
            system_prompt="你是一个短视频脚本拆解专家。输出要简洁、结构化、可直接作为模板参考。",
            user_message=prompt,
            temperature=0.5,
        )
        return result.strip()
    except Exception as e:
        return f"拆解失败: {e}"


def collect_and_store(
    niche: str,
    llm_call,
    threshold_likes: int = 10000,
    max_videos: int = 10,
    use_popular: bool = False,
    custom_keyword: str = "",
) -> dict:
    """
    采集 + 拆解 + 入库 一条龙

    参数:
        niche: 赛道名称
        llm_call: LLM 调用函数
        threshold_likes: 点赞阈值
        max_videos: 最多采集数量
        use_popular: True=热门列表, False=关键词搜索

    返回:
        {"added": N, "skipped": N, "errors": N, "videos": [...]}
    """
    # 1. 获取视频列表
    if use_popular:
        raw_videos = get_popular_videos(ps=max_videos)
    else:
        keyword = custom_keyword if custom_keyword else NICHE_KEYWORDS.get(niche, niche)
        raw_videos = search_videos(keyword, limit=max_videos)

    if not raw_videos:
        source_desc = "B站热门" if use_popular else f"B站搜索「{custom_keyword or NICHE_KEYWORDS.get(niche, niche)}」"
        return {
            "added": 0, "skipped": 0, "errors": 0, "videos": [],
            "message": f"❌ 未获取到视频 — {source_desc} 返回了空结果。\n\n可能原因：① B站 API 限流或拦截（Streamlit Cloud 海外服务器）② 关键词无匹配结果 ③ 网络超时\n\n💡 建议：切换为「热门榜单」模式试试，或降低点赞阈值。"
        }

    # 2. 筛选爆款
    added, skipped, errors = 0, 0, 0
    results = []

    # 检查已存在的 URL（去重）
    existing = db.get_all(500)
    existing_urls = {c.get("url", "") for c in existing}

    for v in raw_videos:
        # 去重
        if v["url"] in existing_urls:
            skipped += 1
            continue

        # 搜索模式下，收藏数不准确，通过视频详情 API 获取真实点赞数
        if not use_popular:
            enriched = _enrich_video_stats(v["bvid"])
            if enriched:
                v["likes_raw"] = enriched["likes_raw"]
                v["views_raw"] = enriched["views_raw"]
                v["comments_raw"] = enriched["comments_raw"]
                v["likes"] = _fmt_num(enriched["likes_raw"])
                v["views"] = _fmt_num(enriched["views_raw"])
                v["comments"] = _fmt_num(enriched["comments_raw"])
            time.sleep(0.3)  # 详情API限速

        # 判断是否爆款（用原始数值比较）
        likes = v.get("likes_raw", 0)
        if isinstance(likes, str):
            try:
                likes = float(likes)
            except ValueError:
                likes = 0

        if likes < threshold_likes:
            skipped += 1
            continue

        # 3. 拆解脚本
        analysis = analyze_script_structure(v, llm_call)
        time.sleep(0.5)  # 限速

        # 4. 入库
        case = {
            "title": v["title"],
            "url": v["url"],
            "platform": v["platform"],
            "niche": niche,
            "views": v.get("views", "0"),
            "likes": v.get("likes", "0"),
            "comments": v.get("comments", "0"),
            "duration": v.get("duration", ""),
            "author": v.get("author", ""),
            "description": v.get("description", ""),
            "tags": v.get("tags", []),
            "script_analysis": analysis,
            "source": "自动采集",
        }
        db.add_case(case)
        added += 1
        results.append(case)

    return {
        "added": added,
        "skipped": skipped,
        "errors": errors,
        "videos": results,
        "message": f"新增 {added} 条，跳过 {skipped} 条（未达阈值/已存在）",
    }


def _is_blocked(resp) -> bool:
    """检测 B站 API 是否被风控拦截（返回 HTML 而非 JSON）"""
    content_type = resp.headers.get("Content-Type", "")
    if "text/html" in content_type or "<html" in resp.text[:200].lower():
        return True
    return False


def _fmt_num(n) -> str:
    """格式化数字（B站 API 返回的是原始数字）"""
    if isinstance(n, str):
        return n
    if n >= 10000:
        return f"{n / 10000:.1f}万"
    return str(n)


def _enrich_video_stats(bvid: str) -> dict | None:
    """通过视频详情 API 获取真实播放/点赞/评论数据"""
    try:
        resp = requests.get(
            BILIBILI_VIDEO_INFO,
            params={"bvid": bvid},
            headers=BILIBILI_HEADERS,
            timeout=4,
        )
        if _is_blocked(resp):
            return None
        data = resp.json()
        if data.get("code") != 0:
            return None
        stat = data.get("data", {}).get("stat", {})
        return {
            "views_raw": stat.get("view", 0),
            "likes_raw": stat.get("like", 0),
            "comments_raw": stat.get("reply", 0),
        }
    except Exception:
        return None
