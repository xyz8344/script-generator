"""
采集器模块 — 自动抓取B站热门视频并拆解脚本结构
"""
import requests
import time
import hashlib
import urllib.parse
import functools
from datetime import datetime
from typing import Optional
import knowledge_db as db


# --- B站 API ---
BILIBILI_SEARCH = "https://api.bilibili.com/x/web-interface/wbi/search/type"
BILIBILI_POPULAR = "https://api.bilibili.com/x/web-interface/popular"
BILIBILI_VIDEO_INFO = "https://api.bilibili.com/x/web-interface/view"
BILIBILI_NAV = "https://api.bilibili.com/x/web-interface/nav"
BILIBILI_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Referer": "https://www.bilibili.com",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "zh-CN,zh;q=0.9",
    "Cookie": "buvid3=auto; buvid4=auto; buvid_fp=auto",  # 基础标识，降低风控概率
}

# WBI 签名相关
WBI_MIX_TABLE = [
    46, 47, 18, 2, 53, 8, 23, 32, 15, 50, 10, 31, 58, 3, 45, 35,
    27, 43, 5, 49, 33, 9, 42, 19, 29, 28, 14, 39, 12, 38, 41, 13,
    37, 48, 7, 16, 24, 55, 40, 61, 26, 17, 0, 1, 60, 51, 30, 4,
    22, 25, 54, 21, 56, 59, 6, 63, 11, 36, 20, 62, 57, 44, 52,
]
_wbi_key_cache: Optional[str] = None
_wbi_key_time: float = 0

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


# --- WBI 签名 ---
def _get_wbi_key() -> str:
    """获取 WBI 签名密钥（缓存 30 分钟）"""
    global _wbi_key_cache, _wbi_key_time
    now = time.time()
    if _wbi_key_cache and (now - _wbi_key_time) < 1800:
        return _wbi_key_cache

    try:
        resp = requests.get(BILIBILI_NAV, headers=BILIBILI_HEADERS, timeout=10)
        if _is_blocked(resp):
            return ""
        data = resp.json()
        wbi_img = data.get("data", {}).get("wbi_img", {})
        img_url = wbi_img.get("img_url", "")
        sub_url = wbi_img.get("sub_url", "")
        # 从URL提取文件名（去掉路径和扩展名）
        img_key = img_url.rsplit("/", 1)[-1].split(".")[0] if img_url else ""
        sub_key = sub_url.rsplit("/", 1)[-1].split(".")[0] if sub_url else ""
        if not img_key or not sub_key:
            return ""
        raw = img_key + sub_key
        mix_key = "".join(raw[i] for i in WBI_MIX_TABLE if i < len(raw))[:32]
        _wbi_key_cache = mix_key
        _wbi_key_time = now
        return mix_key
    except Exception:
        return _wbi_key_cache or ""


def _sign_params(params: dict) -> dict:
    """为请求参数添加 WBI 签名（w_rid + wts）"""
    mix_key = _get_wbi_key()
    if not mix_key:
        return params  # 无法签名，原样返回

    params["wts"] = int(time.time())
    # 按 key 排序
    sorted_keys = sorted(params.keys())
    query_parts = []
    for k in sorted_keys:
        v = params[k]
        # URL 编码，但 ~ 不编码（与 B站 js 行为一致）
        encoded = urllib.parse.quote(str(v), safe="~")
        query_parts.append(f"{k}={encoded}")
    query_string = "&".join(query_parts)
    w_rid = hashlib.md5((query_string + mix_key).encode()).hexdigest()
    params["w_rid"] = w_rid
    return params


def search_videos(keyword: str, limit: int = 20, max_age_days: int = 0) -> list[dict]:
    """搜索B站视频（WBI 签名，海外服务器可用）

    参数:
        max_age_days: 只保留最近 N 天发布的视频，0 = 不限
    """
    now_ts = int(time.time())
    cutoff_ts = now_ts - max_age_days * 86400 if max_age_days > 0 else 0

    videos = []
    for page in range(1, 4):  # 最多翻 3 页
        params = {
            "search_type": "video",
            "keyword": keyword,
            "order": "pubdate",  # 按最新发布排序，配合时间过滤
            "duration": 0,       # 0=全部时长
            "page": page,
            "page_size": 50,     # 每页50条，减少翻页次数
        }
        params = _sign_params(params)
        try:
            resp = requests.get(
                BILIBILI_SEARCH, params=params,
                headers=BILIBILI_HEADERS, timeout=15
            )
            if _is_blocked(resp):
                print("[collector] 搜索被B站风控拦截，返回了验证页面")
                break
            data = resp.json()
            if data.get("code") != 0:
                print(f"[collector] 搜索API返回错误: code={data.get('code')}, message={data.get('message', '')}")
                break

            results = data.get("data", {}).get("result", [])
            if not results:
                break

            for item in results:
                # 时间过滤：pubdate 超出窗口则跳过
                pubdate = item.get("pubdate", 0)
                if cutoff_ts and pubdate < cutoff_ts:
                    continue  # 还在窗口中，但这条太老；因为是 pubdate 倒序，后续可能还有更新的

                if isinstance(pubdate, int) and pubdate > 0:
                    pubdate_str = datetime.fromtimestamp(pubdate).strftime("%Y-%m-%d")
                else:
                    pubdate_str = ""

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
                    "likes_raw": favorites,
                    "comments_raw": review,
                    "views": _fmt_num(play),
                    "likes": _fmt_num(favorites),
                    "comments": _fmt_num(review),
                    "duration": item.get("duration", ""),
                    "author": item.get("author", ""),
                    "url": f"https://www.bilibili.com/video/{bvid}",
                    "platform": "B站",
                    "pubdate": pubdate,
                    "pubdate_str": pubdate_str,
                })

                if len(videos) >= limit * 2:  # 多取一些，补偿 enrich 后的筛选损失
                    return videos

            # 检查是否最后一页的结果已经超出时间窗口
            if cutoff_ts and results:
                last_pubdate = results[-1].get("pubdate", 0)
                if last_pubdate < cutoff_ts:
                    break  # 最后一页尾部已超出窗口，无需翻页

        except Exception as e:
            print(f"[collector] 搜索失败 (page={page}): {e}")
            break

        time.sleep(0.3)  # 翻页限速

    return videos


def get_popular_videos(pn: int = 1, ps: int = 30, max_age_days: int = 0) -> list[dict]:
    """获取B站热门视频

    参数:
        max_age_days: 只保留最近 N 天发布的视频，0 = 不限
    """
    now_ts = int(time.time())
    cutoff_ts = now_ts - max_age_days * 86400 if max_age_days > 0 else 0

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

            pubdate = item.get("pubdate", 0)
            if isinstance(pubdate, int) and pubdate > 0:
                pubdate_str = datetime.fromtimestamp(pubdate).strftime("%Y-%m-%d")
            else:
                pubdate_str = ""

            # 时间过滤（热门榜可能有 pubdate）
            if cutoff_ts and pubdate and pubdate < cutoff_ts:
                continue

            videos.append({
                "bvid": item.get("bvid", ""),
                "title": item.get("title", ""),
                "description": item.get("desc", ""),
                "tags": [],
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
                "pubdate": pubdate,
                "pubdate_str": pubdate_str,
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
    max_age_days: int = 7,
) -> dict:
    """
    采集 + 拆解 + 入库 一条龙

    参数:
        niche: 赛道名称
        llm_call: LLM 调用函数
        threshold_likes: 点赞阈值
        max_videos: 最多采集数量
        use_popular: True=热门列表, False=关键词搜索
        max_age_days: 只保留最近 N 天发布的视频，0 = 不限（默认 7 天）
        custom_keyword: 自定义搜索关键词

    返回:
        {"added": N, "skipped": N, "errors": N, "videos": [...]}
    """
    # 1. 获取视频列表
    if use_popular:
        raw_videos = get_popular_videos(ps=max(max_videos, 30), max_age_days=max_age_days)
    else:
        keyword = custom_keyword if custom_keyword else NICHE_KEYWORDS.get(niche, niche)
        raw_videos = search_videos(keyword, limit=max_videos, max_age_days=max_age_days)

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
                # 补充 pubdate（搜索 API 的 pubdate 可能不准，详情 API 更可靠）
                if enriched.get("pubdate"):
                    v["pubdate"] = enriched["pubdate"]
                    v["pubdate_str"] = datetime.fromtimestamp(enriched["pubdate"]).strftime("%Y-%m-%d")
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
            "pubdate": v.get("pubdate", 0),
            "pubdate_str": v.get("pubdate_str", ""),
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
    """通过视频详情 API 获取真实播放/点赞/评论数据 + 发布时间"""
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
        pubdate = data.get("data", {}).get("pubdate", 0)
        return {
            "views_raw": stat.get("view", 0),
            "likes_raw": stat.get("like", 0),
            "comments_raw": stat.get("reply", 0),
            "pubdate": pubdate,
        }
    except Exception:
        return None
