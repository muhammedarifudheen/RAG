# Import model modules here so Alembic autogenerate can see them.
from app.models.audit import KnowledgeAudit
from app.models.base import Base
from app.models.chat import SharedChat
from app.models.code_graph import (
    EDGE_KINDS,
    EMBEDDING_DIM,
    SOURCE_KINDS,
    SYMBOL_KINDS,
    Edge,
    File,
    Source,
    Symbol,
)
from app.models.integrations import Webhook
from app.models.kg import KG_EDGE_KINDS, KG_NODE_KINDS, KgEdge, KgNode
from app.models.knowledge import AnswerLog, KnowledgeSignal
from app.models.security import ApiKey, AuditEvent
from app.models.versions import HealthSnapshot, SourceVersion

__all__ = [
    "EDGE_KINDS",
    "EMBEDDING_DIM",
    "KG_EDGE_KINDS",
    "KG_NODE_KINDS",
    "SOURCE_KINDS",
    "SYMBOL_KINDS",
    "AnswerLog",
    "ApiKey",
    "AuditEvent",
    "Base",
    "Edge",
    "File",
    "HealthSnapshot",
    "KgEdge",
    "KgNode",
    "KnowledgeAudit",
    "KnowledgeSignal",
    "SharedChat",
    "Source",
    "SourceVersion",
    "Symbol",
    "Webhook",
]
