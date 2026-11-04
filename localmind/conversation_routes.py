"""Authenticated history management; these endpoints never run a chat turn."""
from typing import Annotated

from fastapi import Header, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from .conversations import ConversationError


class ConversationPatch(BaseModel):
    model_config = ConfigDict(extra='forbid')
    title: str | None = Field(default=None, min_length=1, max_length=80)
    draft: str | None = Field(default=None, max_length=2000)
    context: dict | None = None


class ConversationDelete(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    confirmed: bool = False


class HistoryImport(BaseModel):
    model_config = ConfigDict(extra='forbid')
    migration_id: str = Field(min_length=64, max_length=64, pattern='^[a-f0-9]{64}$')
    items: list[dict] = Field(max_length=40)


def install_conversation_routes(app, authorize, server_instance):
    # Resolve the active store at request time. Tests/lifespans can substitute
    # isolated stores without accidentally talking to the user's real journal.
    from . import server

    @app.get('/api/conversations')
    def list_conversations(x_localmind_key: Annotated[str | None, Header()] = None):
        authorize(x_localmind_key)
        try:
            return {'conversations': server.conversations.list(), 'server_instance': server_instance}
        except ConversationError as exc:
            raise HTTPException(409, str(exc)) from exc

    @app.patch('/api/conversations/{conversation_id}')
    def update_conversation(conversation_id: str, data: ConversationPatch,
                            x_localmind_key: Annotated[str | None, Header()] = None):
        authorize(x_localmind_key)
        try:
            return {**server.conversations.update(conversation_id, **data.model_dump(exclude_unset=True)),
                    'server_instance': server_instance}
        except ConversationError as exc:
            raise HTTPException(409, str(exc)) from exc

    @app.delete('/api/conversations/{conversation_id}')
    def delete_conversation(conversation_id: str, data: ConversationDelete,
                            x_localmind_key: Annotated[str | None, Header()] = None):
        authorize(x_localmind_key)
        try:
            server.conversations.delete(conversation_id, confirmed=data.confirmed)
            return {'ok': True}
        except ConversationError as exc:
            raise HTTPException(409, str(exc)) from exc

    @app.post('/api/conversations/import')
    def import_conversations(data: HistoryImport, x_localmind_key: Annotated[str | None, Header()] = None):
        authorize(x_localmind_key)
        try:
            return server.conversations.import_legacy(data.items, data.migration_id)
        except ConversationError as exc:
            raise HTTPException(409, str(exc)) from exc
