import json
import logging
from typing import Sequence, List

from langchain_core.chat_history import BaseChatMessageHistory
from langchain_core.messages import (
    BaseMessage,
    message_to_dict,
    messages_from_dict,
)
from motor.motor_asyncio import AsyncIOMotorClient
from pymongo.errors import ConnectionFailure, OperationFailure, WriteError

logger = logging.getLogger(__name__)

DEFAULT_DBNAME = "chat_history"
DEFAULT_COLLECTION_NAME = "message_store"


class AsyncMongoDBChatMessageHistory(BaseChatMessageHistory):
    """Async chat message history that stores history in MongoDB using Motor.
    
    This class provides asynchronous methods to interact with MongoDB for storing and retrieving chat messages.
    """

    def __init__(
        self,
        connection_string: str,
        session_id: str,
        database_name: str = DEFAULT_DBNAME,
        collection_name: str = DEFAULT_COLLECTION_NAME,
    ):
        self.connection_string = connection_string
        self.session_id = session_id
        self.database_name = database_name
        self.collection_name = collection_name

        try:
            self.client: AsyncIOMotorClient = AsyncIOMotorClient(connection_string)
        except ConnectionFailure as error:
            logger.error(error)

        self.db = self.client[database_name]
        self.collection = self.db[collection_name]

    async def aadd_messages(self, messages: Sequence[BaseMessage]) -> None:
        """Async method to add a list of messages to MongoDB."""
        documents = [{"SessionId": self.session_id, "History": json.dumps(message_to_dict(message))} for message in messages]
        try:
            await self.collection.insert_many(documents)
        except WriteError as err:
            logger.error(err)

    async def aget_messages(self) -> List[BaseMessage]:
        """Async method to retrieve messages from MongoDB."""
        try:
            cursor = self.collection.find({"SessionId": self.session_id})
            documents = await cursor.to_list(length=None)
            if documents:
                items = [json.loads(document["History"]) for document in documents]
            else:
                items = []
        except OperationFailure as error:
            logger.error(error)
            items = []

        messages = messages_from_dict(items)
        return messages

    async def aclear(self) -> None:
        """Async method to clear session messages from MongoDB."""
        try:
            await self.collection.delete_many({"SessionId": self.session_id})
        except WriteError as err:
            logger.error(err)

    def clear(self) -> None:
        pass

    def add_message(self, message: BaseMessage) -> None:
        pass
