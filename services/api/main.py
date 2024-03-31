import os
import uvicorn
from contextlib import asynccontextmanager
from fastapi import Depends, FastAPI, Request
from fastapi.responses import JSONResponse
from twilio.request_validator import RequestValidator
from pydantic import BaseModel
from typing import Optional
import traceback
import asyncio
import json
from fastapi.security import HTTPBasic
from supabase_py_async import AsyncClient, create_client
from supabase_py_async.lib.client_options import ClientOptions

from mongo.db_ops import AsyncMongoMemoryManager, MessageType, MongoDBManager, SessionManager, ChatManager, SwitchManager, AnalyticsManager

import b2chat
import twilio_messaging
import chains
import helpers
from logger import async_logger, shutdown_logger


ACCOUNT_SID = os.environ['TWILIO_ACCOUNT_SID']
AUTH_TOKEN = os.environ['TWILIO_AUTH_TOKEN']

MONGO_CONNECTION_STRING = os.environ['MONGO_CONNECTION_STRING']
DB = MongoDBManager(MONGO_CONNECTION_STRING, "CreditsPanama")
API_KEY_CREDITS_PANAMA = os.getenv("API_KEY_CREDITS_PANAMA", "error")

SUPABASE_URL = os.environ['SUPABASE_URL']
SUPABASE_KEY = os.environ['SUPABASE_KEY']

supabase_client: AsyncClient | None = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        await init_supabase()
        yield
    finally:
        await shutdown_logger()

security = HTTPBasic()
app = FastAPI(lifespan=lifespan)
conversations = {}
conversations_lock = asyncio.Lock()  # Initialize the lock

class Message(BaseModel):
    message: str
    author: str
    conversation: str
    dni_number: Optional[str] = None

@app.exception_handler(Exception)
async def generic_exception_handler(request: Request, exc: Exception):
    # Format the exception and its traceback
    exc_traceback = ''.join(traceback.format_exception(type(exc), exc, exc.__traceback__))
    
    # Log the formatted exception traceback
    await async_logger.error(f"Unhandled exception: {exc_traceback}")

    return JSONResponse(
        status_code=500,
        content={"message": "Internal Server Error"},
    )

async def init_supabase():
    global supabase_client
    supabase_client = await create_client(
            SUPABASE_URL,
            SUPABASE_KEY,
            options=ClientOptions(postgrest_client_timeout=10, storage_client_timeout=10)
    )

async def get_session_manager():
    session_manager = SessionManager(DB)
    await session_manager.ensure_unique_session_index()

    return SessionManager(DB)

async def get_chat_manager():
    chat_manager = ChatManager(DB)
    await chat_manager.ensure_unique_indexes()
    return chat_manager

async def get_switch_manager():
    return SwitchManager(DB)

async def get_analytics_manager():
    return AnalyticsManager(DB)

async def get_mongo_manager():
    return AsyncMongoMemoryManager(DB)

@app.get("/ping")
async def ping() -> str:
    return "pong"

@app.post("/b0cef29f-ec80-47ad-a5d3-80a8b8616a80")
async def handle_incoming_message_agent(request: Request) -> str:
    chat_manager = await get_chat_manager()
    session_manager = await get_session_manager()
    json_data = await request.json()
    memory_manager = await get_mongo_manager()

    
    for message in json_data.get('messages', []):
        if 'text' in message and 'chat' in message and 'chat_id' in message['chat']:
            message_text = message['text']
            chat_id = message['chat']['chat_id']

            conversation_number = await chat_manager.get_conversation_number(chat_id)
            phone_number = await chat_manager.get_phone_number(chat_id)

            if conversation_number:
                await memory_manager.add_message_permament(message_text, conversation_number, MessageType.B2CHAT_AGENT, phone_number)
                twilio_messaging.send_answer_to_client(message_text, conversation_number)

    for event in json_data.get('events', []):
        if 'type' in event and 'chat' in event and 'chat_id' in event['chat']:
            event_type = event['type']
            chat_id = event['chat']['chat_id']
            conversation_number = await chat_manager.get_conversation_number(chat_id)
            phone_number = await chat_manager.get_phone_number(chat_id)

            if event_type == 'CLOSED_CHAT':
                if conversation_number:
                    twilio_messaging.send_answer_to_client("El agente ha cerrado el chat.", conversation_number)
                    await memory_manager.add_message_permament("El agente ha cerrado el chat.", conversation_number, MessageType.B2CHAT_AGENT, phone_number)
                    await session_manager.clear_unprocessed_media_urls(conversation_number)
                await chat_manager.delete_chat_by_id(chat_id)
            elif event_type == 'ASSIGNED_AGENT':
                if conversation_number:
                    await memory_manager.add_message_permament("El agente ha abierto el chat, ahora estás hablando con un agente.", conversation_number, MessageType.B2CHAT_AGENT, phone_number)
                    twilio_messaging.send_answer_to_client("El agente ha abierto el chat, ahora estás hablando con un agente.", conversation_number)
                await chat_manager.update_assigned_agent(chat_id)
            elif event_type == 'AGENT_STARTED_CHAT':
                if conversation_number:
                    await memory_manager.add_message_permament("El agente ha abierto el chat, ahora estás hablando con un agente.", conversation_number, MessageType.B2CHAT_AGENT, phone_number)
                    twilio_messaging.send_answer_to_client("El agente ha abierto el chat, ahora estás hablando con un agente.", conversation_number)
                await chat_manager.update_assigned_agent(chat_id)
            elif event_type == 'AGENT_UNAVAILABLE':
                await async_logger.warn("Problem B2Chat AGENT_UNAVAILABLE")
                if conversation_number:
                    await memory_manager.add_message_permament("Los agentes están actualmente no disponibles, nos pondremos en contacto contigo tan pronto como uno esté disponible.", conversation_number, MessageType.B2CHAT_AGENT, phone_number)
                    twilio_messaging.send_answer_to_client("Los agentes están actualmente no disponibles, nos pondremos en contacto contigo tan pronto como uno esté disponible.", conversation_number)
                await chat_manager.delete_chat_by_id(chat_id)
            elif event_type == 'CHAT_UNAVAILABLE':
                await async_logger.warn("Problem B2Chat CHAT_UNAVAILABLE")
                if conversation_number:
                    await memory_manager.add_message_permament("Hay un problema con la plataforma que están utilizando los agentes, actualmente no están disponibles.", conversation_number, MessageType.B2CHAT_AGENT, phone_number)
                    twilio_messaging.send_answer_to_client("Hay un problema con la plataforma que están utilizando los agentes, actualmente no están disponibles.", conversation_number)
                await chat_manager.delete_chat_by_id(chat_id)

    return str("Ok")

@app.post("/e510fa23-138a-457f-9577-69b58aa1b24b")
async def handle_incoming_message_client(
        request: Request,
        session_manager = Depends(get_session_manager),
        chat_manager = Depends(get_chat_manager),
        switch_manager = Depends(get_switch_manager),
    ) -> str:
    form_data = await request.form()
    data_dict = dict(form_data)

    twilio_signature = request.headers.get('x-twilio-signature')
    validator = RequestValidator(AUTH_TOKEN)

    if not validator.validate("https://credit-api.ponx.ai/e510fa23-138a-457f-9577-69b58aa1b24b", form_data, twilio_signature):
        await async_logger.warning(f"Hacking Attempt with request: {request}")
        return "Ok" 

    memory = await get_mongo_manager()

    if 'Body' in data_dict:
        dni = helpers.find_dni(data_dict['Body'])
        media_urls = await session_manager.get_unprocessed_media_urls(data_dict['ConversationSid'])

        if dni is not None and len(media_urls) > 0:
            await b2chat.agent_handover(chat_manager, dni, data_dict['ConversationSid'], "Client has sent an image", data_dict['Author'])
            await session_manager.insert_or_update_session_dni(data_dict['ConversationSid'], dni)
            id = await chat_manager.get_chat_id(data_dict['ConversationSid'])

            for media_entry in media_urls:
                url = media_entry['url']
                media_type = media_entry['type']
                if media_type == "IMAGE":
                    await b2chat.post_image_to_agent(chat_manager, url, id, supabase_client, SUPABASE_URL)
                    await memory.add_message_permament(url, data_dict['ConversationSid'], MessageType.B2CHAT_CLIENT, data_dict['Author'])

                else:
                    await b2chat.post_file_to_agent(chat_manager, url, id, supabase_client, SUPABASE_URL)
                    await memory.add_message_permament(url, data_dict['ConversationSid'], MessageType.B2CHAT_CLIENT, data_dict['Author'])
            
            await memory.add_message_permament(data_dict['Body'], data_dict['ConversationSid'], MessageType.B2CHAT_CLIENT, data_dict['Author'])
            await b2chat.post_message_to_agent(chat_manager, data_dict['Body'], id)

            ret_msg = "Un agente se pondrá en contacto contigo pronto."
            twilio_messaging.send_answer_to_client(ret_msg, data_dict['ConversationSid'])

            return "Ok"

    if 'Media' in data_dict and data_dict['Media']:
        session_manager = await get_session_manager()
        dni = await session_manager.get_session_dni(data_dict['ConversationSid'])
        if dni:
            await media_flow(data_dict, dni)
        else:
            async with conversations_lock:
                if conversations.get(data_dict['Author'], {}).get('timer_task') is not None:
                    conversations[data_dict['Author']]['timer_task'].cancel()
                    del conversations[data_dict['Author']]

            media_type = ""
            media_items = json.loads(data_dict['Media'])
            for media in media_items:
                content_type = media.get("ContentType")
                if content_type and content_type.startswith("image/"):
                    media_type = "IMAGE"
                else:
                    media_type = "FILE"

                media = await twilio_messaging.fetch_media_by_sid(media['Sid'], data_dict['ChatServiceSid'])
                media = json.loads(media)
                url = media['links']['content_direct_temporary']
                await session_manager.add_unprocessed_media_url(data_dict['ConversationSid'], url, media_type)

            ret_msg = "Antes de poder enviar una imagen o archivo al agente, por favor ingresa tu número de cédula. Con \"-\" en el formato X-XXX-XXXX."
            memory = await get_mongo_manager()
            await memory.add_message_memory(f"{media_type}_MESSAGE", data_dict['ConversationSid'], MessageType.HUMAN, data_dict['Author'])
            await memory.add_message_memory(ret_msg, data_dict['ConversationSid'], MessageType.AI, data_dict['Author'])
            twilio_messaging.send_answer_to_client(ret_msg, data_dict['ConversationSid'])
        return "Ok"


    message = Message(message=data_dict['Body'], author=data_dict['Author'], conversation=data_dict['ConversationSid'])
    id = await chat_manager.get_chat_id(message.conversation) 
    if id:
        await memory.add_message_permament(message.message, message.conversation, MessageType.B2CHAT_CLIENT, message.author)
        await b2chat.post_message_to_agent(chat_manager, message.message, id)
        return "Ok"

    bot_on = await switch_manager.check_off_switch()

    if not bot_on:
         await b2chat.agent_handover(chat_manager, "Bot off", message.conversation, "off-switch-triggered", message.author)
         id = await chat_manager.get_chat_id(message.conversation)
         await memory.add_message_permament(message.message, message.conversation, MessageType.B2CHAT_CLIENT, message.author)
         await b2chat.post_message_to_agent(chat_manager, message.message, id)
         return "Ok"

    sender_id = data_dict['Author']
    async with conversations_lock:
        # Check if the sender already has a conversation
        if sender_id not in conversations:
            # If not, initialize their conversation and timer
            conversations[sender_id] = {'messages': [message], 'timer_task': None}
        else:
            # If yes, append the message to their existing conversation
            conversations[sender_id]['messages'].append(message)
        
        # Manage the timer
        if conversations[sender_id]['timer_task'] is not None:
            # If there's an existing timer, cancel it
            conversations[sender_id]['timer_task'].cancel()
        
        # Always start a new timer task for the latest message
        conversations[sender_id]['timer_task'] = asyncio.create_task(start_timer(sender_id, 16))

    return "Ok"


async def start_timer(sender_id, duration):
    print("start_timer() hit")
    await asyncio.sleep(duration)
    print("sleep over")
    await process_and_respond(sender_id)


async def process_and_respond(sender_id: str):
    """
    Process the buffered messages for a given sender_id and respond.
    This function simulates processing and must be replaced with actual logic.
    """
    print("process_and respond()")
    async with conversations_lock:
        if sender_id not in conversations:
            print("Sender ID not in conversations, returning early.")
            return
        # Clone the necessary data while inside the lock
        messages = conversations[sender_id]['messages'].copy()
        del conversations[sender_id]  # Clear the conversation once cloned

    # Now that we're outside the lock, we can perform the longer operations
    print("Processing and responding...")
    combined_message = " ".join([msg.message for msg in messages])
    messages[0].message = combined_message  # Assuming modification of the first message for demonstration
    print(f"1: {messages}")
    chat_manager = await get_chat_manager()
    print("2")
    # Check if agent handover has already occured
    id = await chat_manager.get_chat_id(messages[0].conversation) 
    print("3")
    if not id:
        ret = await execute_message(messages[0])
        print(f"Responding to {sender_id} with messages: {messages[0]}")
        twilio_messaging.send_answer_to_client(ret, messages[0].conversation)
    else:
        print("Posting to b2c")
        memory = await get_mongo_manager()
        await memory.add_message_permament(messages[0].message, messages[0].conversation, MessageType.B2CHAT_CLIENT, messages[0].author)
        await b2chat.post_message_to_agent(chat_manager, messages[0].message, id)



async def execute_message(
        message: Message,
    ) -> str:
    print("execute_message()")
    chat_manager = await get_chat_manager()
    session_manager = await get_session_manager()
    analytics_manager = await get_analytics_manager()
    mongo_memory_manager = await get_mongo_manager()

    await analytics_manager.increment_count_month()

    intent_restart = await chains.indicate_intent_restart(message.message)

    if intent_restart == "Y" or intent_restart == "y":
        await mongo_memory_manager.clear(message.conversation)
        await mongo_memory_manager.add_message_permament(message.message, message.conversation, MessageType.HUMAN, message.author) 
        await mongo_memory_manager.add_message_permament("El chat ha sido reiniciado.", message.conversation, MessageType.AI, message.author) 
        await session_manager.delete_session_by_id(message.conversation)
        return "El chat ha sido reiniciado."

    memory = await mongo_memory_manager.load_buffer(message.conversation)
    print(memory)

    await mongo_memory_manager.add_message_memory(message.message, message.conversation, MessageType.HUMAN, message.author)

    message.dni_number = await session_manager.get_session_dni(message.conversation)
    ret = " "
    if message.dni_number is None:
        message.dni_number = helpers.find_dni(message.message)
        if message.dni_number is None:
            ret = await chains.get_dni_conv_chain(message.message, memory)
        else:
            await session_manager.insert_or_update_session_dni(message.conversation, message.dni_number)
            user_context = await helpers.get_user_context(message.dni_number, API_KEY_CREDITS_PANAMA)
            
            if 'msg' in user_context:
                await session_manager.delete_session_by_id(message.conversation)
                if 'msg-agent' in user_context:
                    await b2chat.agent_handover(chat_manager, message.dni_number, message.conversation, user_context['msg-agent'], message.author)
                return user_context['msg']
                
            answer_vec = await chains.provide_support_conv_chain(message.message, memory, user_context)

            for item in answer_vec:
                for key, value in item.items():
                    if key == "Cliente":
                        print(f"Sending message to client: {value}")
                        ret = value
                    elif key == "Agente":
                        #ret = "Un agente se pondrá en contacto contigo pronto."
                        await b2chat.agent_handover(chat_manager, message.dni_number, message.conversation, value, message.author)
                        print(f"Sending message to agent: {value}")
    else:
        user_context = await helpers.get_user_context(message.dni_number, API_KEY_CREDITS_PANAMA)
    
        if 'msg' in user_context:
            await session_manager.delete_session_by_id(message.conversation)
            if 'msg-agent' in user_context:
                await b2chat.agent_handover(chat_manager, message.dni_number, message.conversation, user_context['msg-agent'], message.author)
            return user_context['msg']

        answer_vec = await chains.provide_support_conv_chain(message.message, memory, user_context)

        for item in answer_vec:
            for key, value in item.items():
                if key == "Cliente":
                    print(f"Sending message to client: {value}")
                    ret = value
                elif key == "Agente":
                    #ret = "Un agente se pondrá en contacto contigo pronto."
                    await b2chat.agent_handover(chat_manager, message.dni_number, message.conversation, value, message.author)
                    print(f"Sending message to agent: {value}")
    
    if ret == " ":
        ret = "Un agente se pondrá en contacto contigo pronto."

    await mongo_memory_manager.add_message_memory(ret, message.conversation, MessageType.AI, message.author)

    return str(ret)

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)

async def media_flow(data_dict: dict, dni: str):
        chat_manager = await get_chat_manager()
        memory = await get_mongo_manager()

        # Parse the 'Media' field from the JSON string
        media_items = json.loads(data_dict['Media'])
        chat_service_sid = data_dict['ChatServiceSid']

        # Iterate over each media item
        for media in media_items:
            content_type = media.get("ContentType")
            if content_type and content_type.startswith("image/"):
                media = await twilio_messaging.fetch_media_by_sid(media['Sid'], chat_service_sid)
                media = json.loads(media)

                id = await chat_manager.get_chat_id(data_dict['ConversationSid']) 
                if id:
                    await b2chat.post_image_to_agent(chat_manager, media['links']['content_direct_temporary'], id, supabase_client, SUPABASE_URL)
                    await memory.add_message_permament(media['links']['content_direct_temporary'], data_dict['ConversationSid'], MessageType.B2CHAT_CLIENT, data_dict['Author'])

                else:
                    await b2chat.agent_handover(chat_manager, dni, data_dict['ConversationSid'], "Image", data_dict['Author'])

                    id = await chat_manager.get_chat_id(data_dict['ConversationSid'])
                    await b2chat.post_image_to_agent(chat_manager, media['links']['content_direct_temporary'], id, supabase_client, SUPABASE_URL)
                    await memory.add_message_permament(media['links']['content_direct_temporary'], data_dict['ConversationSid'], MessageType.B2CHAT_CLIENT, data_dict['Author'])

                    twilio_messaging.send_answer_to_client("Un agente se pondrá en contacto contigo pronto.", data_dict['ConversationSid'])

            elif content_type and content_type.startswith("audio/"):
                print(f"Found audio media: SID {media['Sid']}, Type {media['ContentType']}")
                media = await twilio_messaging.fetch_media_by_sid(media['Sid'], chat_service_sid)
                media = json.loads(media)

                id = await chat_manager.get_chat_id(data_dict['ConversationSid']) 
                if id:
                    await b2chat.post_file_to_agent(chat_manager, media['links']['content_direct_temporary'], id, supabase_client, SUPABASE_URL)
                    await memory.add_message_permament(media['links']['content_direct_temporary'], data_dict['ConversationSid'], MessageType.B2CHAT_CLIENT, data_dict['Author'])

                else:
                    await b2chat.agent_handover(chat_manager, dni, data_dict['ConversationSid'], "File", data_dict['Author'])

                    id = await chat_manager.get_chat_id(data_dict['ConversationSid'])

                    await b2chat.post_file_to_agent(chat_manager, media['links']['content_direct_temporary'], id, supabase_client, SUPABASE_URL)
                    await memory.add_message_permament(media['links']['content_direct_temporary'], data_dict['ConversationSid'], MessageType.B2CHAT_CLIENT, data_dict['Author'])

                    twilio_messaging.send_answer_to_client("Un agente se pondrá en contacto contigo pronto.", data_dict['ConversationSid']) 
            else:
                print(f"Found non-image media or unknown type: SID {media['Sid']}")

        return "Ok"
