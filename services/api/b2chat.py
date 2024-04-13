import os
from pydantic import Json
import aiohttp
from aiohttp import BasicAuth
import datetime
import uuid
from pydantic import BaseModel, Field

from supabase_py_async import AsyncClient
from helpers import extract_numbers, fetch_and_upload_file
from logger import async_logger
import twilio_messaging

from mongo.db_ops import ChatManager

user = os.environ.get('B2C_USER')
pwd = os.environ.get('B2C_PASS')

class MobileNumber(BaseModel):
    country_calling_code: str
    number: str

class Contact(BaseModel):
    full_name: str
    identification: int
    mobile_number: MobileNumber = Field(..., alias="mobileNumber")

async def get_access_token():
    url = 'https://api.b2chat.io/oauth/token'
    auth = BasicAuth(user, pwd) 
    data = {
        'grant_type': 'client_credentials'
    }
    headers = {
        'Content-Type': 'application/x-www-form-urlencoded'
    }

    async with aiohttp.ClientSession() as session:
        async with session.post(url, data=data, auth=auth, headers=headers) as response:
            if response.status == 200:
                json_response = await response.json()
                return json_response.get('access_token')
            else:
                await async_logger.error(f"b2chat.get_access_token() response:{response.status}")
                return f"Error: {response.status}"

async def post_chat(access_token: str, chat_id, contact: Contact, initial_msg: str):
    url = f'https://api.b2chat.io/bots/{chat_id}/chat' if chat_id else 'https://api.b2chat.io/bots/chat'
    headers = {
        'Content-Type': 'application/json',
        'Authorization': f'Bearer {access_token}'
    }
    now = datetime.datetime.now()
    formatted_time = int(now.timestamp())
    unique_id = str(uuid.uuid4())

    if contact and not chat_id:
        contact_dict = contact.dict(by_alias=True)
        data = {
            "contact": contact_dict,
            "bot_chat": [
                {
                    "datetime": formatted_time,
                    "message_id": unique_id,
                    "text": initial_msg,
                    "from": {
                        "full_name": "BOT-A-AGENTE",
                        "is_bot": True
                    },
                    "to": {
                        "full_name": "Client",
                        "is_bot": False
                    }
                }
            ]
        }
    else:
       data = {
            "bot_chat": [
                {
                    "datetime": formatted_time,
                    "message_id": unique_id,
                    "text": initial_msg,
                    "from": {
                        "full_name": "BOT-A-AGENTE",
                        "is_bot": True
                    },
                    "to": {
                        "full_name": "Client",
                        "is_bot": False
                    }
                }
            ]
        }

    
    async with aiohttp.ClientSession() as session:
        async with session.post(url, headers=headers, json=data) as response:
            print(f"Raw \n\n: {headers} {data}")
            json_response = await response.json()
            if response.status in [200, 201]:
                return json_response
            else:
                await async_logger.error(f"b2chat.post_chat() response:{json_response}")
                return None 

async def agent_handover(chat_manager: ChatManager, dni_number: str, conversation_id: str, initial_msg: str, whatsapp_number: str):
    access_token = await get_access_token()

    ### Check if contact is new
    chat_id = await chat_manager.get_chat_id(conversation_id)
    if not chat_id:
        result = extract_numbers(whatsapp_number)
        if result:
            country_code, national_number = result
        else:
            country_code = 57
            national_number = 000000000

        contact = Contact (
            full_name=dni_number,
            identification=33,
            number=MobileNumber(
                country_calling_code=country_code,
                number=national_number, 
            )
        )
    else:
        contact = None

    response = await post_chat(access_token, chat_id, contact, initial_msg)
    if response:
        if not chat_id:
            chat_id = response['chat_id']
            await chat_manager.insert_chat_id(chat_id, conversation_id, whatsapp_number) 
        else:
            await chat_manager.set_direct_to_agent_true(chat_id) 
    else:
        twilio_messaging.send_answer_to_client("Estamos enfrentando un problema de nuestra parte, no se pudo abrir la conexión con el agente, estamos investigándolo.", conversation_id)

async def post_message_to_agent(chat_manager: ChatManager, msg: str, chat_id: str) -> Json:
    access_token = await get_access_token()
    
    url = f'https://api.b2chat.io/bots/{chat_id}/textMessage' 
    headers = {
        'Content-Type': 'application/json',
        'Authorization': f'Bearer {access_token}'
    }
    data = {
        "text": msg
    }

    async with aiohttp.ClientSession() as session:
        async with session.post(url, headers=headers, json=data) as response:
            json_response = await response.json()
            if response.status in [200, 201]:
                return json_response

            await async_logger.error(f"b2chat.post_message_to_agent() response:{json_response}")
            conversation = await chat_manager.get_conversation_number(chat_id)
            twilio_messaging.send_answer_to_client("Estamos enfrentando un problema de nuestra parte, la conexión con el agente se ha cerrado, estamos investigándolo.", conversation)
            await chat_manager.set_direct_to_agent_false(chat_id)

async def post_image_to_agent(chat_manager: ChatManager, image_url: str, chat_id: str, client, supabase_url: str) -> Json:
    access_token = await get_access_token()

    uploaded_url = await fetch_and_upload_file(image_url, "wap_images", client, supabase_url)
    
    url = f'https://api.b2chat.io/bots/{chat_id}/sendImage' 
    headers = {
        'Content-Type': 'application/json',
        'Authorization': f'Bearer {access_token}'
    }
    data = {
        "url": uploaded_url 
    }

    async with aiohttp.ClientSession() as session:
        async with session.post(url, headers=headers, json=data) as response:
            json_response = await response.json()
            if response.status in [200, 201]:
                return json_response

            await async_logger.error(f"b2chat.post_image_to_agent() response:{json_response}")
            conversation = await chat_manager.get_conversation_number(chat_id)
            twilio_messaging.send_answer_to_client("Estamos enfrentando un problema de nuestra parte, la conexión con el agente se ha cerrado, estamos investigándolo.", conversation)
            await chat_manager.set_direct_to_agent_false(chat_id)

async def post_file_to_agent(chat_manager: ChatManager, file_url: str, chat_id: str, client: AsyncClient, supabase_url: str) -> Json:
    access_token = await get_access_token()

    uploaded_url = await fetch_and_upload_file(file_url, "wap_files", client, supabase_url)
    
    url = f'https://api.b2chat.io/bots/{chat_id}/sendFile' 
    headers = {
        'Content-Type': 'application/json',
        'Authorization': f'Bearer {access_token}'
    }
    data = {
        "url": uploaded_url
    }

    async with aiohttp.ClientSession() as session:
        async with session.post(url, headers=headers, json=data) as response:
            json_response = await response.json()
            if response.status in [200, 201]:
                return json_response

            await async_logger.error(f"b2chat.post_file_to_agent() response:{json_response}")
            conversation = await chat_manager.get_conversation_number(chat_id)
            twilio_messaging.send_answer_to_client("Estamos enfrentando un problema de nuestra parte, la conexión con el agente se ha cerrado, estamos investigándolo.", conversation)
            await chat_manager.set_direct_to_agent_false(chat_id)
