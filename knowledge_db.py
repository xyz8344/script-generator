"""
知识库模块 — 管理爆款案例的存储、检索
"""
import json
import os
import re
from datetime import datetime, timedelta
from typing import Optional

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
DB_PATH = os.path.join(DATA_DIR, "cases.json")


def _ensure_dir():
    os.makedirs(DATA_DIR, exist_ok=True)


def _load() -> list[dict]:
    """加载全部案例"""
    _ensure_dir()
    if not os.path.exists(DB_PATH):
        return []
    with open(DB_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def _save(cases: list[dict]):
    _ensure_dir()
    with open(DB_PATH, "w", encoding="utf-8") as f:
        json.dump(cases, f, ensure_ascii=False, indent=2)


def add_case(case: dict) -> str:
    """添加一条案例，返回 case_id"""
    cases = _load()
    case["id"] = f"case_{len(cases) + 1:04d}"
    case["created_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    cases.append(case)
    _save(cases)
    return case["id"]


def delete_case(case_id: str) -> bool:
    """删除案例"""
    cases = _load()
    new = [c for c in cases if c["id"] != case_id]
    if len(new) == len(cases):
        return False
    _save(new)
    return True


def search(query: str, niche: str = "", limit: int = 5) -> list[dict]:
    """关键词搜索案例（简单倒排索引）"""
    cases = _load()
    if not cases:
        return []

    query_lower = query.lower()
    keywords = _tokenize(query_lower)

    scored = []
    for c in cases:
        score = 0
        # 标题匹配
        title = c.get("title", "").lower()
        for kw in keywords:
            if kw in title:
                score += 3
        # 描述匹配
        desc = c.get("description", "").lower()
        for kw in keywords:
            if kw in desc:
                score += 2
        # 赛道匹配
        if niche and niche in c.get("niche", ""):
            score += 5
        # 标签匹配
        tags = " ".join(c.get("tags", [])).lower()
        for kw in keywords:
            if kw in tags:
                score += 1

        if score > 0:
            scored.append((score, c))

    scored.sort(key=lambda x: x[0], reverse=True)
    return [item[1] for item in scored[:limit]]


def get_recent(days: int = 7, limit: int = 50) -> list[dict]:
    """获取最近 N 天的案例"""
    cases = _load()
    cutoff = datetime.now() - timedelta(days=days)
    recent = []
    for c in cases:
        ts = c.get("created_at", "")
        try:
            dt = datetime.strptime(ts, "%Y-%m-%d %H:%M:%S")
            if dt >= cutoff:
                recent.append(c)
        except ValueError:
            pass
    return recent[:limit]


def get_all(limit: int = 100) -> list[dict]:
    """获取全部案例"""
    return _load()[-limit:]


def count() -> dict:
    """知识库统计"""
    cases = _load()
    niches = {}
    for c in cases:
        n = c.get("niche", "未分类")
        niches[n] = niches.get(n, 0) + 1
    return {
        "total": len(cases),
        "by_niche": niches,
        "last_updated": cases[-1]["created_at"] if cases else "暂无",
    }


def format_for_prompt(cases: list[dict], max_cases: int = 3) -> str:
    """将案例格式化为可嵌入 Prompt 的文本"""
    if not cases:
        return "（暂无参考案例）"

    parts = []
    for i, c in enumerate(cases[:max_cases], 1):
        parts.append(f"""### 参考案例 {i}：{c.get('title', '无标题')}
- 平台：{c.get('platform', '未知')}
- 赛道：{c.get('niche', '未分类')}
- 数据：{c.get('views', '?')} 播放 · {c.get('likes', '?')} 点赞
- 脚本结构拆解：
{c.get('script_analysis', '暂无拆解')}
""")
    return "\n---\n".join(parts)


def _tokenize(text: str) -> list[str]:
    """简单中文分词（按字切 + 2-gram）"""
    # 去掉标点
    text = re.sub(r"[^\w一-鿿]", " ", text)
    # 按空格分
    words = text.split()
    # 对中文部分做 2-gram
    result = []
    for w in words:
        if len(w) <= 1:
            if w:
                result.append(w)
        else:
            result.append(w)  # 完整词
            for i in range(len(w) - 1):
                result.append(w[i:i + 2])  # 2-gram
    return result[:20]  # 限制数量
