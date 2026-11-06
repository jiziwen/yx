"""导入/发布短事务与检索；原文私有，版本不可变，引用提交前复核有效性。"""

import hashlib
import io
import json

from sqlalchemy import func, or_, select

from app.core.db import now, uid
from app.core.errors import DomainError
from app.core.plugins import load_symbol
from app.integrations.embeddings import DevelopmentEmbedding, tokens
from app.modules.media_jobs.governance import aware
from app.modules.operations.models import Audit

from .models import KnowledgeChunk, KnowledgeDocument, KnowledgeIndexJob, KnowledgeVersion


def embedder(app, audit_context=None):
    """可信插件懒装配；测试哈希须显式启用且标明，不能静默替代真实模型。"""
    config = app.state.config["knowledge"]
    development = app.state.settings.knowledge_development_embedding
    provider = (
        DevelopmentEmbedding({}, app.state.settings)
        if development
        else load_symbol(config["embedding_entrypoint"])(config["embedding_options"], app.state.settings)
    )
    return app.state.model_calls.wrap(
        provider,
        "knowledge-embedding",
        {
            "kind": "embedding",
            "development_only": development,
            "options": {"model": provider.spec["model"]},
        },
        audit_context,
    )


def spec(app):
    """指纹含插件入口和参数摘要，阻止相同模型名的不同空间误混用。"""
    provider = embedder(app)
    source = app.state.config["knowledge"]
    digest = hashlib.sha256(
        json.dumps(
            {
                "entrypoint": source["embedding_entrypoint"],
                "options": source["embedding_options"],
                "spec": provider.spec,
            },
            sort_keys=True,
        ).encode()
    ).hexdigest()
    return {
        **provider.spec,
        "fingerprint": digest,
        "tokenizer": "zh-bigram-en-v1",
        "pipeline": "plain-pdf-v1",
    }


def active_filter():
    """所有客户查询共用发布资格：当前指针、ready、批准、有效期、未撤销。"""
    return [
        KnowledgeDocument.published_version_id == KnowledgeVersion.id,
        KnowledgeVersion.status == "ready",
        KnowledgeVersion.approved_at.is_not(None),
        KnowledgeVersion.revoked_at.is_(None),
        or_(KnowledgeVersion.valid_from.is_(None), KnowledgeVersion.valid_from <= now()),
        or_(KnowledgeVersion.valid_until.is_(None), KnowledgeVersion.valid_until > now()),
    ]


def document(db, document_id, lock=False):
    """后台文档锁只序列化同一文档的导入/发布，不锁外部网络。"""
    query = select(KnowledgeDocument).where(KnowledgeDocument.id == document_id)
    item = db.scalar(query.with_for_update() if lock else query)
    if item is None:
        raise DomainError("NOT_FOUND", "知识文档不存在", 404)
    return item


def decode_source(content, format, limit):
    """有界纯文本/PDF解析；不抓取链接、不执行脚本，扫描PDF明确拒绝。"""
    try:
        if format in {"md", "txt"}:
            text = content.decode("utf-8-sig")
        elif format == "pdf":
            from pypdf import PdfReader

            reader = PdfReader(io.BytesIO(content), strict=True)
            if reader.is_encrypted or len(reader.pages) > 100:
                raise ValueError("pdf bounds")
            parts = []
            size = 0
            for index, page in enumerate(reader.pages):
                part = page.extract_text() or ""
                size += len(part)
                if size > limit:
                    raise ValueError("text bounds")
                parts.append(f"【第{index + 1}页】\n" + part)
            text = "\n\n".join(parts)
            if sum(len(p.strip()) for p in parts) < 20:
                raise ValueError("no text layer")
        else:
            raise ValueError("unsupported")
        text = text.replace("\x00", "").strip()
        if not text or len(text) > limit:
            raise ValueError("text bounds")
        return text
    except Exception as exc:
        raise DomainError(
            "KNOWLEDGE_INVALID_SOURCE",
            "仅支持有界 UTF-8 Markdown/TXT 或有文本层 PDF；扫描件请先转换为文本",
            422,
        ) from exc


def import_version(app, db, actor, document_id, body, content=None, format="txt"):
    """相同请求键同内容返回原版本；先校验版本，私有原文再写入，不触发图片任务。"""
    doc = document(db, document_id, lock=True)
    content = content if content is not None else body.text.encode()
    cfg = app.state.config["knowledge"]
    if len(content) > cfg["max_source_bytes"]:
        raise DomainError("KNOWLEDGE_SOURCE_TOO_LARGE", "知识原文过大", 422)
    decode_source(content, format, cfg["max_text_chars"])
    digest = hashlib.sha256(
        content + body.model_dump_json(exclude={"expected_revision", "request_key", "text"}).encode()
    ).hexdigest()
    previous = db.scalar(
        select(KnowledgeVersion).where(
            KnowledgeVersion.document_id == doc.id, KnowledgeVersion.request_key == body.request_key
        )
    )
    if previous:
        if previous.content_hash != digest:
            raise DomainError("IDEMPOTENCY_CONFLICT", "相同请求键的原文或元数据发生变化")
        return previous
    if doc.revision != body.expected_revision:
        raise DomainError("REVISION_CONFLICT", "知识文档版本已变化，请刷新")
    version_id = uid()
    key = f"knowledge/{doc.id}/{version_id}.{format}"
    app.state.gateway.get("storage").put(key, content)
    version = KnowledgeVersion(
        id=version_id,
        document_id=doc.id,
        version_no=doc.revision + 1,
        request_key=body.request_key,
        content_hash=digest,
        title=body.title,
        summary=body.summary,
        category=body.category,
        source_key=key,
        source_format=format,
        embedding_spec=spec(app),
        actor_id=actor.id,
        valid_from=body.valid_from,
        valid_until=body.valid_until,
    )
    db.add(version)
    db.flush()
    db.add(KnowledgeIndexJob(version_id=version.id))
    doc.revision += 1
    db.add(
        Audit(
            actor_id=actor.id,
            action="knowledge.import",
            resource_id=doc.id,
            summary={"version_id": version.id, "version_no": version.version_no},
        )
    )
    db.commit()
    return version


def publish(db, actor, document_id, body, *, remove=False):
    """显式管理员操作；同一锁内校验 revision、资格和发布指针，失败不影响旧版。"""
    doc = document(db, document_id, lock=True)
    if doc.revision != body.expected_revision:
        raise DomainError("REVISION_CONFLICT", "知识文档版本已变化，请刷新")
    version = db.get(KnowledgeVersion, body.version_id)
    if version is None or version.document_id != doc.id:
        raise DomainError("NOT_FOUND", "知识版本不存在", 404)
    if remove:
        if doc.published_version_id != version.id:
            raise DomainError("KNOWLEDGE_NOT_PUBLISHED", "该版本不是当前发布版本")
        doc.published_version_id = None
        version.revoked_at = now()
    else:
        if (
            version.status != "ready"
            or version.revoked_at
            or (version.valid_from and aware(version.valid_from) > now())
            or (version.valid_until and aware(version.valid_until) <= now())
        ):
            raise DomainError("KNOWLEDGE_NOT_READY", "索引未就绪、已撤销或不在有效期内，不能发布")
        version.approved_at = now()
        doc.published_version_id = version.id
    doc.revision += 1
    db.add(
        Audit(
            actor_id=actor.id,
            action="knowledge.unpublish" if remove else "knowledge.publish",
            resource_id=doc.id,
            summary={"version_id": version.id, "revision": doc.revision},
        )
    )
    db.commit()
    return doc


def guide_rows(db):
    """用户列表只读取正式版本的标题/摘要，未发布草稿不可见。"""
    return db.scalars(
        select(KnowledgeVersion)
        .join(KnowledgeDocument, KnowledgeDocument.id == KnowledgeVersion.document_id)
        .where(*active_filter())
        .order_by(KnowledgeVersion.title)
    ).all()


def search(app, db, query, vector=None, embedding_spec=None):
    """中文同分词关键词 + pgvector精确召回，RRF合并；向量故障标记关键词降级。"""
    cfg = app.state.config["knowledge"]
    terms = list(dict.fromkeys(tokens(query)))[:160]
    meaningful = [term for term in terms if len(term) > 1]
    terms = meaningful or terms
    base = (
        select(KnowledgeChunk, KnowledgeVersion)
        .join(KnowledgeVersion, KnowledgeVersion.id == KnowledgeChunk.version_id)
        .join(KnowledgeDocument, KnowledgeDocument.id == KnowledgeVersion.document_id)
        .where(*active_filter())
    )
    # 小知识库有界读取用于 SQLite；PG 在服务器上分别召回，避免全库向量出库。
    lexical = []
    semantic = []
    if db.bind.dialect.name == "postgresql":
        ts = func.to_tsvector("simple", KnowledgeChunk.search_text)
        tsquery = func.to_tsquery("simple", " | ".join(terms)) if terms else None
        if tsquery is not None:
            lexical = list(
                db.execute(
                    base.where(ts.op("@@")(tsquery))
                    .order_by(func.ts_rank_cd(ts, tsquery).desc(), KnowledgeChunk.id)
                    .limit(cfg["recall_limit"])
                )
            )
        if vector is not None:
            distance = KnowledgeChunk.embedding.cosine_distance(vector)
            semantic = list(
                db.execute(
                    base.where(
                        KnowledgeVersion.embedding_spec["fingerprint"].as_string()
                        == embedding_spec["fingerprint"],
                        distance <= 1 - cfg["min_similarity"],
                    )
                    .order_by(distance, KnowledgeChunk.id)
                    .limit(cfg["recall_limit"])
                )
            )
    else:
        rows = list(db.execute(base.limit(2001)))
        if len(rows) > 2000:
            raise DomainError("KNOWLEDGE_CAPACITY", "本地知识量超过开发检索上限，请使用PostgreSQL", 503)
        lexical = sorted(
            [row for row in rows if set(terms) & set(row[0].search_text.split())],
            key=lambda row: (-len(set(terms) & set(row[0].search_text.split())), row[0].id),
        )[: cfg["recall_limit"]]
        if vector is not None:
            scored = [
                (sum(a * b for a, b in zip(vector, row[0].embedding)), row)
                for row in rows
                if row[1].embedding_spec["fingerprint"] == embedding_spec["fingerprint"]
            ]
            semantic = [
                row
                for score, row in sorted(scored, key=lambda item: (-item[0], item[1][0].id))
                if score >= cfg["min_similarity"]
            ][: cfg["recall_limit"]]
    scores = {}
    values = {}
    for ranking in (lexical, semantic):
        for rank, row in enumerate(ranking):
            chunk, version = row
            values[chunk.id] = row
            scores[chunk.id] = scores.get(chunk.id, 0) + 1 / (61 + rank)
    evidence = []
    for chunk_id in sorted(scores, key=lambda key: (-scores[key], key))[: cfg["result_limit"]]:
        chunk, version = values[chunk_id]
        evidence.append(
            {
                "chunk_id": chunk.id,
                "document_id": version.document_id,
                "version_id": version.id,
                "version_no": version.version_no,
                "title": version.title,
                "locator": chunk.locator,
                "text": chunk.text[:700],
            }
        )
    return {
        "strategy": "hybrid-rrf-v1" if vector is not None else "keyword-fallback-v1",
        "development_sample": bool((embedding_spec or spec(app)).get("development_sample")),
        "evidence": evidence,
    }


def citation_evidence(db, observations, selected):
    """只允许引用本轮实际检索片段，最终锁住发布指针复核下架/换版/过期。"""
    available = {
        item["chunk_id"]: item
        for obs in observations
        if obs["name"] == "search_knowledge" and obs["status"] == "ok"
        for item in (obs.get("data") or {}).get("evidence", [])
    }
    if len(set(selected)) != len(selected) or any(key not in available for key in selected):
        raise DomainError("KNOWLEDGE_INVALID_CITATION", "引用不属于本轮检索证据", 422)
    result = []
    for key in sorted(available):
        item = available[key]
        doc = document(db, item["document_id"], lock=True)
        version = db.scalar(
            select(KnowledgeVersion)
            .join(KnowledgeDocument, KnowledgeDocument.id == KnowledgeVersion.document_id)
            .where(KnowledgeVersion.id == item["version_id"], *active_filter())
        )
        chunk = db.get(KnowledgeChunk, key)
        if (
            not version
            or not chunk
            or doc.published_version_id != version.id
            or chunk.version_id != version.id
            or chunk.text[:700] != item["text"]
        ):
            raise DomainError("KNOWLEDGE_CHANGED", "知识来源已下架、换版或过期，请重新查询")
        if key in selected:
            result.append(item)
    return sorted(result, key=lambda item: selected.index(item["chunk_id"]))
