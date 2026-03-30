from __future__ import annotations

import math
import re
from collections import Counter, defaultdict
from dataclasses import dataclass

import jieba

from app.services.document_parser import ParsedDocument, TextChunk

ROLE_ORDER = ["goal", "method", "result", "conclusion"]
ROLE_LABELS = {
    "goal": "研究焦点",
    "method": "方法路径",
    "result": "核心结果",
    "conclusion": "结论价值",
    "detail": "关键信息",
}
ROLE_KEYWORDS = {
    "goal": [
        "aim",
        "aims",
        "goal",
        "goals",
        "objective",
        "objectives",
        "motivation",
        "problem",
        "focus",
        "investigate",
        "study",
        "explore",
        "address",
        "purpose",
        "目标",
        "目的",
        "问题",
        "研究",
        "探讨",
        "聚焦",
        "关注",
        "旨在",
        "针对",
    ],
    "method": [
        "method",
        "methods",
        "approach",
        "framework",
        "model",
        "algorithm",
        "pipeline",
        "architecture",
        "design",
        "propose",
        "proposed",
        "develop",
        "developed",
        "present",
        "using",
        "based",
        "方法",
        "模型",
        "框架",
        "算法",
        "流程",
        "设计",
        "构建",
        "建立",
        "提出",
        "采用",
        "结合",
        "利用",
        "基于",
    ],
    "result": [
        "result",
        "results",
        "show",
        "shows",
        "showed",
        "demonstrate",
        "demonstrates",
        "demonstrated",
        "improve",
        "improves",
        "improved",
        "outperform",
        "achieve",
        "achieved",
        "experiment",
        "experiments",
        "performance",
        "finding",
        "findings",
        "结果",
        "实验",
        "表明",
        "显示",
        "提升",
        "提高",
        "优于",
        "性能",
        "效果",
        "准确率",
        "显著",
    ],
    "conclusion": [
        "conclusion",
        "conclude",
        "concludes",
        "suggest",
        "suggests",
        "indicate",
        "indicates",
        "implication",
        "implications",
        "potential",
        "valuable",
        "clinical",
        "evidence",
        "application",
        "结论",
        "说明",
        "证明",
        "提示",
        "价值",
        "临床",
        "应用",
        "意义",
        "可行",
        "潜力",
    ],
}
STOPWORDS = {
    "the",
    "a",
    "an",
    "and",
    "or",
    "of",
    "for",
    "to",
    "in",
    "on",
    "with",
    "by",
    "from",
    "using",
    "use",
    "based",
    "this",
    "that",
    "these",
    "those",
    "our",
    "their",
    "his",
    "her",
    "its",
    "is",
    "are",
    "was",
    "were",
    "be",
    "been",
    "being",
    "as",
    "at",
    "it",
    "we",
    "they",
    "he",
    "she",
    "them",
    "also",
    "can",
    "may",
    "into",
    "than",
    "such",
    "via",
    "between",
    "within",
    "across",
    "through",
    "there",
    "here",
    "paper",
    "study",
    "article",
    "research",
    "how",
    "main",
    "goal",
    "goals",
    "feature",
    "features",
    "investigate",
    "investigates",
    "investigated",
    "combine",
    "combines",
    "combined",
    "framework",
    "本文",
    "本研究",
    "本论文",
    "本文中",
    "以及",
    "其中",
    "我们",
    "研究",
    "结果",
    "方法",
    "进行",
    "采用",
    "通过",
    "为了",
    "一种",
    "一个",
    "可以",
    "能够",
    "具有",
    "相关",
    "主要",
    "工作",
    "分析",
    "模型",
}


@dataclass
class ScoredChunk:
    text: str
    location: str
    score: float


@dataclass
class CandidateSentence:
    text: str
    location: str
    source: str
    order: int
    role: str
    score: float


def analyze_documents(documents: list[ParsedDocument], topic: str) -> list[dict]:
    analyzed: list[dict] = []

    for document in documents:
        topic_profile = _build_topic_profile(f"{topic} {document.title}")
        title_profile = _build_topic_profile(document.title)
        candidate_sentences = _collect_candidate_sentences(document)
        scored_sentences = _score_sentences(candidate_sentences, topic_profile, title_profile)
        role_map = _select_role_sentences(scored_sentences)
        top_chunks = _score_chunks(document.chunks, topic_profile, scored_sentences)
        bullets = _build_bullets(document, role_map, scored_sentences)
        overview = _build_overview_sentence(document, role_map, scored_sentences)

        analyzed.append(
            {
                "document": document,
                "top_chunks": top_chunks[:4],
                "top_sentences": scored_sentences[:8],
                "role_map": role_map,
                "bullets": bullets,
                "overview": overview,
                "score": round(_document_score(top_chunks, role_map), 2),
            }
        )

    analyzed.sort(key=lambda item: item["score"], reverse=True)
    return analyzed


def build_global_summary(topic: str, analyzed_documents: list[dict]) -> list[str]:
    if not analyzed_documents:
        return [f"未找到与“{topic}”相关的有效文档内容。"]

    single_document = len(analyzed_documents) == 1
    focus_terms = _collect_focus_terms(topic, analyzed_documents)
    method_clauses = _collect_role_clauses(analyzed_documents, "method")
    result_clauses = _collect_role_clauses(analyzed_documents, "result")
    conclusion_clauses = _collect_role_clauses(analyzed_documents, "conclusion")

    summary: list[str] = []
    if single_document:
        overview = analyzed_documents[0].get("overview", "")
        if overview:
            summary.append(f"研究概览：{summarize_text(overview, 132)}。")
    elif focus_terms:
        summary.append(f"研究范围：围绕“{topic}”，文档内容主要集中在{_join_terms(focus_terms)}。")

    if method_clauses:
        summary.append(f"方法脉络：{_join_clauses(method_clauses[:2])}。")

    if result_clauses:
        summary.append(f"核心发现：{_join_clauses(result_clauses[:2])}。")
    elif conclusion_clauses:
        summary.append(f"总体结论：{_join_clauses(conclusion_clauses[:2])}。")

    representative = []
    for item in analyzed_documents[:3]:
        document = item["document"]
        authors = _shorten_authors(document.authors)
        representative.append(f"{document.title}（{authors}）")
    if representative:
        summary.append(f"代表文献：{'；'.join(representative)}。")

    if not summary:
        summary.append(f"围绕“{topic}”的摘要整理已完成，但文档文本质量较弱，建议上传更清晰的论文原文。")

    return summary[:5]


def summarize_text(text: str, limit: int) -> str:
    text = _polish_sentence(text)
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip("，,；;:. ") + "…"


def _collect_candidate_sentences(document: ParsedDocument) -> list[tuple[str, str, str, int]]:
    sentences: list[tuple[str, str, str, int]] = []
    seen: set[str] = set()
    order = 0
    normalized_title = _normalize_sentence(document.title)

    def add_sentences(source_text: str, source: str, location: str) -> None:
        nonlocal order
        for sentence in _split_sentences(source_text):
            cleaned = _polish_sentence(sentence)
            normalized = _normalize_sentence(cleaned)
            if not cleaned or normalized in seen or _looks_like_noise(cleaned):
                continue
            if normalized == normalized_title and source != "title":
                continue
            seen.add(normalized)
            sentences.append((cleaned, location, source, order))
            order += 1

    cleaned_abstract = _strip_heading_metadata(document.abstract, document.title, document.authors)
    add_sentences(cleaned_abstract, "abstract", "摘要")
    for chunk in document.chunks:
        cleaned_chunk = _strip_heading_metadata(chunk.text, document.title, document.authors)
        add_sentences(cleaned_chunk, "body", chunk.location)

    if not sentences and document.full_text:
        add_sentences(_strip_heading_metadata(document.full_text[:1200], document.title, document.authors), "body", "正文概览")
    if not sentences:
        add_sentences(document.title, "title", "标题")

    return sentences


def _score_sentences(
    sentences: list[tuple[str, str, str, int]],
    topic_profile: Counter[str],
    title_profile: Counter[str],
) -> list[CandidateSentence]:
    scored: list[CandidateSentence] = []
    topic_terms = list(topic_profile.keys())
    title_terms = [term for term in title_profile.keys() if term not in STOPWORDS]

    for text, location, source, order in sentences:
        lowered = text.lower()
        tokens = Counter(_tokenize(text))
        role_scores = _role_scores(text)

        topic_score = sum(
            math.log1p(tokens.get(term, 0)) * (1.4 + topic_profile[term] * 0.35)
            for term in topic_terms
        )
        title_score = sum(math.log1p(tokens.get(term, 0)) * 0.55 for term in title_terms)
        direct_phrase_bonus = 2.4 if any(term and len(term) > 2 and term in lowered for term in topic_terms) else 0.0
        source_bonus = {"title": 2.0, "abstract": 2.2, "body": 0.9}.get(source, 0.6)
        position_bonus = max(1.15 - order * 0.035, 0.15)
        length_bonus = _length_bonus(text)
        role_bonus = max(role_scores.values(), default=0.0)
        noise_penalty = _noise_penalty(text)

        score = topic_score + title_score + direct_phrase_bonus + source_bonus + position_bonus + length_bonus + role_bonus
        score -= noise_penalty
        role = _pick_role(role_scores, source, order)

        if score <= 0.9:
            continue

        scored.append(
            CandidateSentence(
                text=text,
                location=location,
                source=source,
                order=order,
                role=role,
                score=score,
            )
        )

    scored.sort(key=lambda item: item.score, reverse=True)
    return scored


def _score_chunks(
    chunks: list[TextChunk],
    topic_profile: Counter[str],
    scored_sentences: list[CandidateSentence],
) -> list[ScoredChunk]:
    if not chunks:
        return []

    sentence_boosts: dict[str, float] = defaultdict(float)
    for sentence in scored_sentences:
        sentence_boosts[sentence.location] = max(sentence_boosts[sentence.location], sentence.score)

    scored_chunks: list[ScoredChunk] = []
    topic_terms = list(topic_profile.keys())
    for chunk in chunks:
        chunk_tokens = Counter(_tokenize(chunk.text))
        overlap_score = sum(
            math.log1p(chunk_tokens.get(term, 0)) * (1 + topic_profile[term] * 0.25)
            for term in topic_terms
        )
        phrase_bonus = 2.0 if any(term and len(term) > 2 and term in chunk.text.lower() for term in topic_terms) else 0.0
        density_bonus = min(len(chunk.text) / 480.0, 1.4)
        sentence_bonus = sentence_boosts.get(chunk.location, 0.0) * 0.72
        final_score = overlap_score + phrase_bonus + density_bonus + sentence_bonus
        if final_score <= 0:
            continue
        scored_chunks.append(ScoredChunk(text=chunk.text, location=chunk.location, score=final_score))

    scored_chunks.sort(key=lambda item: item.score, reverse=True)
    return scored_chunks


def _select_role_sentences(scored_sentences: list[CandidateSentence]) -> dict[str, CandidateSentence]:
    selected: dict[str, CandidateSentence] = {}
    used: set[str] = set()

    for role in ROLE_ORDER:
        for sentence in scored_sentences:
            normalized = _normalize_sentence(sentence.text)
            if sentence.role != role or normalized in used:
                continue
            selected[role] = sentence
            used.add(normalized)
            break

    for sentence in scored_sentences:
        if len(selected) >= 4:
            break
        normalized = _normalize_sentence(sentence.text)
        if normalized in used:
            continue
        selected.setdefault("detail", sentence)
        used.add(normalized)
        break

    return selected


def _build_bullets(
    document: ParsedDocument,
    role_map: dict[str, CandidateSentence],
    scored_sentences: list[CandidateSentence],
) -> list[str]:
    bullets: list[str] = []
    used: set[str] = set()
    used_labels: set[str] = set()
    normalized_title = _normalize_sentence(document.title)

    for role in ROLE_ORDER:
        sentence = role_map.get(role)
        if sentence is None:
            continue
        summary = summarize_text(_format_bullet_text(role, sentence.text), 118)
        normalized = _normalize_sentence(summary)
        if normalized in used or normalized == normalized_title:
            continue
        label = ROLE_LABELS[role]
        bullets.append(f"{label}：{summary}")
        used.add(normalized)
        used_labels.add(label)

    if len(bullets) < 3 and document.abstract:
        abstract_summary = summarize_text(document.abstract, 118)
        normalized = _normalize_sentence(abstract_summary)
        if normalized not in used and normalized != normalized_title:
            bullets.append(f"摘要概览：{abstract_summary}")
            used.add(normalized)
            used_labels.add("摘要概览")

    for sentence in scored_sentences:
        if len(bullets) >= 4:
            break
        summary = summarize_text(_format_bullet_text(sentence.role, sentence.text), 118)
        normalized = _normalize_sentence(summary)
        if normalized in used or normalized == normalized_title:
            continue
        label = ROLE_LABELS.get(sentence.role, "关键信息")
        if label in used_labels:
            label = "关键信息"
        bullets.append(f"{label}：{summary}")
        used.add(normalized)
        used_labels.add(label)

    if not bullets:
        fallback = summarize_text(document.full_text or document.title or "未识别到可用文本。", 118)
        bullets.append(f"内容概览：{fallback}")

    return bullets[:4]


def _build_overview_sentence(
    document: ParsedDocument,
    role_map: dict[str, CandidateSentence],
    scored_sentences: list[CandidateSentence],
) -> str:
    clauses: list[str] = []
    normalized_title = _normalize_sentence(document.title)
    for role in ROLE_ORDER:
        sentence = role_map.get(role)
        if sentence is None:
            continue
        clause = _to_clause(sentence.text, 52)
        if _normalize_sentence(clause) == normalized_title:
            continue
        clauses.append(clause)

    if not clauses and scored_sentences:
        clause = _to_clause(scored_sentences[0].text, 68)
        if _normalize_sentence(clause) != normalized_title:
            clauses.append(clause)

    prefix = document.title if document.title else document.filename
    if clauses:
        return f"{prefix}：{'；'.join(clauses[:3])}"
    return prefix


def _document_score(top_chunks: list[ScoredChunk], role_map: dict[str, CandidateSentence]) -> float:
    chunk_score = sum(chunk.score for chunk in top_chunks[:3])
    role_score = sum(sentence.score for sentence in role_map.values())
    return chunk_score * 0.7 + role_score * 0.45


def _collect_focus_terms(topic: str, analyzed_documents: list[dict]) -> list[str]:
    counter: Counter[str] = Counter()
    topic_terms = set(_build_topic_profile(topic).keys())

    for item in analyzed_documents[:5]:
        document = item["document"]
        role_map = item["role_map"]
        text = " ".join(
            [
                document.title,
                role_map.get("goal").text if role_map.get("goal") else "",
                role_map.get("method").text if role_map.get("method") else "",
            ]
        )
        for token in _tokenize(text):
            if token in STOPWORDS or token in topic_terms:
                continue
            if len(token) < 2:
                continue
            counter[token] += 1

    if not counter:
        return []
    return [term for term, _ in counter.most_common(4)]


def _collect_role_clauses(analyzed_documents: list[dict], role: str) -> list[str]:
    clauses: list[str] = []
    seen: set[str] = set()

    for item in analyzed_documents[:4]:
        sentence = item["role_map"].get(role)
        if sentence is None:
            continue
        clause = _to_clause(sentence.text, 58)
        normalized = _normalize_sentence(clause)
        if normalized in seen:
            continue
        seen.add(normalized)
        clauses.append(clause)

    return clauses


def _join_clauses(clauses: list[str]) -> str:
    cleaned = [clause.rstrip("。.;； ") for clause in clauses if clause]
    return "；".join(cleaned)


def _join_terms(terms: list[str]) -> str:
    if len(terms) == 1:
        return terms[0]
    if len(terms) == 2:
        return f"{terms[0]}和{terms[1]}"
    return "、".join(terms[:-1]) + f"和{terms[-1]}"


def _shorten_authors(authors: str) -> str:
    authors = authors or "未识别作者"
    parts = [part.strip() for part in re.split(r"[;,、]| and ", authors) if part.strip()]
    if not parts:
        return authors
    if len(parts) == 1:
        return parts[0]
    return f"{parts[0]}等"


def _split_sentences(text: str) -> list[str]:
    cleaned = re.sub(r"\s+", " ", (text or "").replace("\u3000", " ")).strip()
    if not cleaned:
        return []

    pieces = re.split(r"(?<=[。！？；!?])\s+|(?<=[.])\s+(?=[A-Z])|(?<=:)\s+(?=[A-Z\u4e00-\u9fff])", cleaned)
    sentences: list[str] = []
    for piece in pieces:
        piece = piece.strip(" \t\r\n-")
        if not piece:
            continue
        if len(piece) > 240:
            subparts = re.split(r"(?<=[，,；;])\s+", piece)
            sentences.extend([sub.strip() for sub in subparts if sub.strip()])
        else:
            sentences.append(piece)
    return sentences


def _polish_sentence(text: str) -> str:
    text = re.sub(r"\s+", " ", (text or "")).strip()
    text = re.sub(r"^(abstract|摘要|keywords?|关键词)[:：\s-]*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"^(introduction|引言|background)[:：\s-]*", "", text, flags=re.IGNORECASE)
    text = text.strip(" -:：;；,.，。")
    return text


def _normalize_sentence(text: str) -> str:
    return re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "", (text or "").lower())


def _looks_like_noise(text: str) -> bool:
    normalized = _normalize_sentence(text)
    if len(normalized) < 12:
        return True
    if re.match(r"^(figure|fig\.|table|图|表)\s*\d+", text, flags=re.IGNORECASE):
        return True
    if re.search(r"https?://|www\.|doi\.org|@[\w\-]+", text, flags=re.IGNORECASE):
        return True
    if re.search(r"\b(references|bibliography|致谢)\b", text, flags=re.IGNORECASE):
        return True
    if sum(char.isdigit() for char in text) > max(len(text) * 0.35, 10):
        return True
    return False


def _role_scores(text: str) -> dict[str, float]:
    lowered = text.lower()
    scores: dict[str, float] = {}
    for role, keywords in ROLE_KEYWORDS.items():
        score = 0.0
        for keyword in keywords:
            if keyword in lowered:
                score += 1.0 if len(keyword) > 2 else 0.45
        scores[role] = score

    if re.search(r"\bwe propose\b|\bwe present\b|提出了|构建了|设计了", lowered):
        scores["method"] += 1.4
    if re.search(r"\bresults?\b|\bshow(s|ed)?\b|表明|显示|优于|提升", lowered):
        scores["result"] += 1.3
    if re.search(r"\bconclusion\b|\bsuggest(s)?\b|说明了|提示了|证明了|具有", lowered):
        scores["conclusion"] += 1.1
    return scores


def _pick_role(role_scores: dict[str, float], source: str, order: int) -> str:
    if source == "title":
        return "goal"

    best_role = max(role_scores.items(), key=lambda item: item[1])[0]
    best_value = role_scores[best_role]
    if best_value > 0:
        return best_role

    if source == "abstract" and order <= 1:
        return "goal"
    if source == "abstract" and order <= 3:
        return "method"
    return "detail"


def _length_bonus(text: str) -> float:
    length = len(text)
    if 26 <= length <= 150:
        return 1.25
    if 151 <= length <= 220:
        return 0.65
    if length < 20:
        return -0.9
    return -0.3


def _noise_penalty(text: str) -> float:
    penalty = 0.0
    if re.search(r"\b(et al\.|vol\.|pp\.|copyright)\b", text, flags=re.IGNORECASE):
        penalty += 1.6
    if re.search(r"\[[0-9,\s]+\]|\([0-9]{4}\)", text):
        penalty += 0.8
    if re.match(r"^(fig|figure|table|图|表)\s*\d+", text, flags=re.IGNORECASE):
        penalty += 2.4
    if len(text) > 240:
        penalty += 0.6
    return penalty


def _strip_heading_metadata(text: str, title: str, authors: str) -> str:
    cleaned = _polish_sentence(text)
    author_parts = [part.strip() for part in re.split(r"[;,、]| and ", authors or "") if part.strip()]
    author_variants = [authors]
    if author_parts:
        author_variants.extend(
            [
                ", ".join(author_parts),
                "; ".join(author_parts),
                " ".join(author_parts),
                " and ".join(author_parts),
                "、".join(author_parts),
            ]
        )

    prefixes = [title, f"{title} {authors}", f"{title}\n{authors}", *author_variants]
    for prefix in prefixes:
        prefix = _polish_sentence(prefix)
        if not prefix:
            continue
        remainder = _remove_prefix_like(cleaned, prefix)
        if remainder is not None and len(_normalize_sentence(remainder)) >= 16:
            cleaned = remainder
    return cleaned


def _remove_prefix_like(text: str, prefix: str) -> str | None:
    if text.lower().startswith(prefix.lower()):
        return text[len(prefix):].strip(" -:：;；,.，。\n")

    tokens = re.findall(r"[A-Za-z]+|[\u4e00-\u9fff]+", prefix)
    if not tokens:
        return None
    pattern = r"^\s*" + r"[\s,;、]+".join(re.escape(token) for token in tokens) + r"[\s,;、]*"
    match = re.match(pattern, text, flags=re.IGNORECASE)
    if match:
        return text[match.end() :].strip(" -:：;；,.，。\n")
    return None


def _format_bullet_text(role: str, text: str) -> str:
    clause = _to_clause(text, 108)
    lowered = clause.lower()

    if role == "goal":
        if re.search(r"^(本文|本研究|该研究|文中|this paper|this study|we )", clause, flags=re.IGNORECASE):
            return clause
        return f"文献重点讨论{clause}"
    if role == "method":
        if re.search(r"(提出|采用|构建|设计|基于|method|approach|framework|model|using|propose)", lowered):
            return clause
        return f"文中采用{clause}"
    if role == "result":
        if re.search(r"(表明|显示|提升|优于|result|results|show|demonstrate|improve|outperform)", lowered):
            return clause
        return f"实验结果表明{clause}"
    if role == "conclusion":
        if re.search(r"(说明|提示|证明|suggest|indicate|conclusion|value|clinical)", lowered):
            return clause
        return f"结论上{clause}"
    return clause


def _to_clause(text: str, limit: int) -> str:
    text = summarize_text(text, limit)
    return text.rstrip("。.;； ")


def _build_topic_profile(topic: str) -> Counter[str]:
    topic = topic.strip()
    tokens = [token for token in _tokenize(topic) if token not in STOPWORDS]
    if topic and topic.lower() not in tokens:
        tokens.append(topic.lower())
    return Counter(tokens)


def _tokenize(text: str) -> list[str]:
    text = text.strip().lower()
    if not text:
        return []

    tokens: list[str] = []
    if re.search(r"[\u4e00-\u9fff]", text):
        tokens.extend([token.strip() for token in jieba.cut(text) if token.strip()])
    tokens.extend(re.findall(r"[a-z0-9][a-z0-9\-\_\.]+", text))
    tokens.extend(re.findall(r"[\u4e00-\u9fff]{2,}", text))
    return tokens
