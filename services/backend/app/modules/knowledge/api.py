"""管理员导入/预览/发布，客户仅读正式指南及自己消息的引用。"""

from typing import Annotated

from fastapi import APIRouter, File, Form, Request, UploadFile
from sqlalchemy import select

from app.core.db import uid
from app.core.errors import DomainError
from app.core.security import DB, AdminDep, UserDep
from app.modules.conversations.models import Conversation, Message
from app.modules.projects.service import require_project

from .models import KnowledgeChunk, KnowledgeDocument, KnowledgeVersion
from .schemas import (
    ChunkPreview,
    CitationView,
    DocumentView,
    GuideView,
    ImportVersion,
    PublishVersion,
    VersionView,
)
from .service import active_filter, document, guide_rows, import_version, publish

router = APIRouter(tags=["knowledge"])


@router.get("/api/v1/admin/knowledge/documents", response_model=list[DocumentView])
def documents(user: AdminDep, db: DB):
    """只读后台列表，当前上限100；具体版本另查。"""
    return db.scalars(
        select(KnowledgeDocument).order_by(KnowledgeDocument.created_at.desc()).limit(100)
    ).all()


@router.post("/api/v1/admin/knowledge/documents", response_model=DocumentView, status_code=201)
def create_document(user: AdminDep, db: DB):
    """创建空壳文档没有客户可见内容。"""
    item = KnowledgeDocument(id=uid(), revision=0)
    db.add(item)
    db.commit()
    return item


@router.get("/api/v1/admin/knowledge/documents/{document_id}/versions", response_model=list[VersionView])
def versions(document_id: str, user: AdminDep, db: DB):
    """管理员预览导入历史；不返回对象存储键。"""
    document(db, document_id)
    return db.scalars(
        select(KnowledgeVersion)
        .where(KnowledgeVersion.document_id == document_id)
        .order_by(KnowledgeVersion.version_no.desc())
        .limit(100)
    ).all()


@router.post(
    "/api/v1/admin/knowledge/documents/{document_id}/versions", response_model=VersionView, status_code=202
)
def import_text(document_id: str, body: ImportVersion, user: AdminDep, db: DB, request: Request):
    """文本入库只创建持久索引任务，发布需要后续明确操作。"""
    return import_version(request.app, db, user, document_id, body)


@router.post(
    "/api/v1/admin/knowledge/documents/{document_id}/files", response_model=VersionView, status_code=202
)
async def import_file(
    document_id: str,
    user: AdminDep,
    db: DB,
    request: Request,
    file: Annotated[UploadFile, File()],
    metadata: Annotated[str, Form()],
):
    """有界上传MD/TXT/带文本PDF，不从文件名推导任何存储路径。"""
    import json

    from pydantic import ValidationError

    try:
        body = ImportVersion.model_validate({**json.loads(metadata), "text": "file"})
    except (ValueError, TypeError, ValidationError) as exc:
        raise DomainError("VALIDATION_ERROR", "导入元数据不正确", 422) from exc
    content = await file.read(request.app.state.config["knowledge"]["max_source_bytes"] + 1)
    format = (file.filename or "").rsplit(".", 1)[-1].lower()
    return import_version(request.app, db, user, document_id, body, content, format)


@router.get("/api/v1/admin/knowledge/versions/{version_id}/preview", response_model=list[ChunkPreview])
def preview(version_id: str, user: AdminDep, db: DB):
    """发布前查看真实分块正文，上限100，不暴露向量。"""
    if not db.get(KnowledgeVersion, version_id):
        raise DomainError("NOT_FOUND", "版本不存在", 404)
    return db.scalars(
        select(KnowledgeChunk)
        .where(KnowledgeChunk.version_id == version_id)
        .order_by(KnowledgeChunk.ordinal)
        .limit(100)
    ).all()


@router.post("/api/v1/admin/knowledge/documents/{document_id}/publish", response_model=DocumentView)
def publish_version(document_id: str, body: PublishVersion, user: AdminDep, db: DB):
    """管理员审核发布，原子资格校验和审计。"""
    return publish(db, user, document_id, body)


@router.post("/api/v1/admin/knowledge/documents/{document_id}/unpublish", response_model=DocumentView)
def unpublish_version(document_id: str, body: PublishVersion, user: AdminDep, db: DB):
    """下架立即停止检索及旧引用查看。"""
    return publish(db, user, document_id, body, remove=True)


@router.get("/api/v1/web/guides", response_model=list[GuideView])
def guides(db: DB):
    """公开已发布指南元数据；草稿标题也不可泄漏。"""
    return [
        {
            "document_id": v.document_id,
            "version_id": v.id,
            "title": v.title,
            "summary": v.summary,
            "category": v.category,
        }
        for v in guide_rows(db)
    ]


@router.get("/api/v1/web/guides/{document_id}", response_model=GuideView)
def guide(document_id: str, db: DB):
    """只提供当前有效版本正文，纯文本由前端转义。"""
    version = next((v for v in guide_rows(db) if v.document_id == document_id), None)
    if not version:
        raise DomainError("NOT_FOUND", "指南未发布或已下架", 404)
    parts = list(
        db.scalars(
            select(KnowledgeChunk.text)
            .where(KnowledgeChunk.version_id == version.id)
            .order_by(KnowledgeChunk.ordinal)
        )
    )
    content = (parts[0] if parts else "") + "".join(part[80:] for part in parts[1:])
    return {
        "document_id": version.document_id,
        "version_id": version.id,
        "title": version.title,
        "summary": version.summary,
        "category": version.category,
        "content": content,
    }


@router.get("/api/v1/web/messages/{message_id}/citations/{index}", response_model=CitationView)
def citation(message_id: str, index: int, user: UserDep, db: DB):
    """可读消息+引用序号授权，不允许任意chunk读取；下架后旧引用也不开放。"""
    message = db.get(Message, message_id)
    conversation = db.get(Conversation, message.conversation_id) if message else None
    if not conversation or conversation.owner_user_id != user.id:
        raise DomainError("NOT_FOUND", "引用不可访问", 404)
    if conversation.project_id:
        project = require_project(db, conversation.project_id, user.id)
        if message.privacy_epoch != project.privacy_epoch:
            raise DomainError("NOT_FOUND", "引用不可访问", 404)
    references = message.citations_json or []
    if not 1 <= index <= len(references):
        raise DomainError("NOT_FOUND", "引用不存在", 404)
    item = references[index - 1]
    valid = db.scalar(
        select(KnowledgeVersion)
        .join(KnowledgeDocument, KnowledgeDocument.id == KnowledgeVersion.document_id)
        .where(KnowledgeVersion.id == item["version_id"], *active_filter())
    )
    if not valid:
        raise DomainError("KNOWLEDGE_CHANGED", "该知识来源已下架、换版或过期", 410)
    return item
