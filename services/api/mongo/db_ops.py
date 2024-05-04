from langchain.memory import ConversationBufferMemory
from motor.motor_asyncio import AsyncIOMotorClient
from typing import Optional
from datetime import datetime
from enum import Enum
from itertools import zip_longest
from logger import async_logger

class MongoDBManager:
    def __init__(self, mongo_uri: str, db_name: str):
        self.client = AsyncIOMotorClient(mongo_uri)
        self.db = self.client[db_name]

    def get_collection(self, collection_name: str):
        return self.db[collection_name]

class SessionManager:
    def __init__(self, db: MongoDBManager):
        self.collection = db.get_collection("session-dni")

    async def insert_or_update_session_dni(self, session_id: str, dni_number: str):
        # Check if a document with the given session_id already exists
        existing_document = await self.collection.find_one({"session_id": session_id})
    
        if existing_document:
            # If the document exists, update it with the new dni_number
            await self.collection.update_one(
                {"session_id": session_id},
                {"$set": {"dni_number": dni_number}}
            )
        else:
            # If the document does not exist, insert a new one
            document = {"session_id": session_id, "dni_number": dni_number, "unprocessed_media_urls": []}
            await self.collection.insert_one(document)

    async def get_session_dni(self, session_id: str) -> Optional[str]:
        document = await self.collection.find_one({"session_id": session_id})
        return document.get("dni_number") if document else None

    async def delete_session_by_id(self, session_id: str):
        await self.collection.delete_many({"session_id": session_id})
    
    async def add_unprocessed_media_url(self, session_id: str, media_url: str, media_type: str):
        # Define the query to match the document by session_id
        query = {"session_id": session_id}
    
        media_info = {"url": media_url, "type": media_type}

        # Define the update operation to append the new media_url to the end of the array
        update_operation = {
                "$push": {"unprocessed_media_urls": media_info},
        }
    
        # Execute the update operation
        await self.collection.update_one(query, update_operation, upsert=True)

    async def get_unprocessed_media_urls(self, session_id: str):
        # Define the query to match the document by session_id
        query = {"session_id": session_id}
    
        # Execute the find operation
        document = await self.collection.find_one(query)
    
        # Check if the document exists and has unprocessed_media_urls field
        if document and "unprocessed_media_urls" in document:
            # Return the unprocessed_media_urls
            return document["unprocessed_media_urls"]
        else:
            # Return an empty list if no document found or no unprocessed_media_urls field exists
            return []

    async def ensure_unique_session_index(self):
        # Create a unique index on the session_id field
        await self.collection.create_index([("session_id", 1)], unique=True)

    async def clear_unprocessed_media_urls(self, session_id: str):
        # Define the query to match the document by session_id
        query = {"session_id": session_id}
    
        # Define the update operation to set unprocessed_media_urls to an empty list
        update_operation = {"$set": {"unprocessed_media_urls": []}}
    
        # Execute the update operation
        await self.collection.update_one(query, update_operation)

class ChatManager:
    def __init__(self, db: MongoDBManager):
        self.collection = db.get_collection("chat-b2c")

    async def ensure_unique_indexes(self):
        await self.collection.create_index([("chat_id", 1)], unique=True)
        await self.collection.create_index([("conversation_number", 1)], unique=True)

    async def insert_chat_id(self, chat_id: str, conversation: str, phone_number: str):
        document = {"chat_id": chat_id, "conversation_number": conversation, "direct_to_agent": True, "phone_number": phone_number}
        await self.collection.insert_one(document)

    async def get_conversation_number(self, chat_id: str) -> Optional[str]:
        document = await self.collection.find_one({"chat_id": chat_id})
        return document.get("conversation_number") if document else None

    async def get_phone_number(self, chat_id: str) -> Optional[str]:
        document = await self.collection.find_one({"chat_id": chat_id})
        return document.get("phone_number") if document else None

    async def get_chat_id(self, conversation_number: str) -> Optional[str]:
        document = await self.collection.find_one({"conversation_number": conversation_number})
        return document.get("chat_id") if document else None

    async def set_direct_to_agent_true(self, chat_id: str):
        await self.collection.update_one({"chat_id": chat_id}, {"$set": {"direct_to_agent": True}})

    async def set_direct_to_agent_false(self, chat_id: str):
        await self.collection.update_one({"chat_id": chat_id}, {"$set": {"direct_to_agent": False}})

    async def get_direct_to_agent(self, chat_id: str) -> bool:
        document = await self.collection.find_one({"chat_id": chat_id})
        return document.get("direct_to_agent", False) if document else False

    async def update_conversation_by_phone(self, conversation: str, phone_number: str):
        filter = {"phone_number": phone_number}
        new_values = {"$set": {"conversation_number": conversation}}
        result = await self.collection.update_one(filter, new_values)


class AnalyticsManager:
    def __init__(self, db: MongoDBManager):
        self.collection = db.get_collection("analtics")

    async def increment_count_month(self):
        formatted_date = datetime.now().strftime('%m/%Y')
        doc = await self.collection.find_one({'formatted_date': formatted_date})
        if doc:
            new_count = doc['counter'] + 1
            await self.collection.update_one({'_id': doc['_id']}, {'$set': {'counter': new_count}})
        else:
            new_count = 1
            await self.collection.insert_one({'formatted_date': formatted_date, 'counter': new_count})

    async def get_current_year_data(self):
        current_year = datetime.now().year
        start_of_year = f"01/{current_year}"
        end_of_year = f"12/{current_year}"
        current_year_data = self.collection.find({'formatted_date': {'$gte': start_of_year, '$lte': end_of_year}})
        return [doc async for doc in current_year_data]

class SwitchManager:
    def __init__(self, db: MongoDBManager):
        self.collection = db.get_collection("switch")

    async def toggle_off_switch(self):
        document_id = 'switch'
        document = await self.collection.find_one({'_id': document_id})
        if document:
            new_state = not document.get('chatbot_on', False)
            await self.collection.update_one({'_id': document_id}, {'$set': {'chatbot_on': new_state}})
        else:
            new_state = True
            await self.collection.insert_one({'_id': document_id, 'chatbot_on': new_state})

    async def check_off_switch(self):
        document_id = 'switch'
        document = await self.collection.find_one({'_id': document_id})
        if document:
            print(f"Document ID '{document_id}' - chatbot_on: {document['chatbot_on']}")
            return document['chatbot_on']
        return True

class MessageType(Enum):
    HUMAN = 'human'
    AI = 'ai'
    B2CHAT_AGENT = 'agent'
    B2CHAT_CLIENT = 'client'

class AsyncMongoMemoryManager:
    def __init__(self, db: MongoDBManager):
        self.collection = db.get_collection("message-store")
        self.collection_permanent = db.get_collection("message-store-permanent")
        
    async def load_buffer(self, session: str) -> ConversationBufferMemory:
        buffer = ConversationBufferMemory()
        cursor = self.collection.find({"session": session})

        documents = await cursor.to_list(length=None)
        if documents:
            items = [document["message"] for document in documents]
        else:
            items = []

        for item1, item2 in zip_longest(items[::2], items[1::2], fillvalue="No response was generated, possible bug"):
            buffer.save_context({"input": item1}, {"output": item2})

        return buffer
   
    async def clear(self, session: str):
        await self.collection.delete_many({"session": session})

    async def add_message_memory(self, message: str, session: str, type: MessageType, number: str):
        type_var = type.value
        await self.collection.insert_one({
            "session": session,
            "message": message,
            "date": datetime.utcnow(),
            "type": type_var,
        })

        await self.add_message_permament(message, session, type, number)

    async def add_message_permament(self, message: str, session: str, type: MessageType, number: str):
        type_var = type.value
        await self.collection_permanent.insert_one({
            "session": session,
            "message": message,
            "date": datetime.utcnow(),
            "type": type_var,
            "phone_number": number
        })

