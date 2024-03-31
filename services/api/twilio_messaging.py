import os
from twilio.rest import Client
import aiohttp

account_sid = os.environ.get('TWILIO_ACCOUNT_SID')
auth_token = os.environ.get('TWILIO_AUTH_TOKEN')

def send_answer_to_client(body: str, conversation: str):
    client = Client(account_sid, auth_token)

    message = client.conversations \
                .v1 \
                .conversations(conversation) \
                .messages \
                .create(author='creditspanama-chatbot', body=body)

    print(message.sid)

async def fetch_media_by_sid(media_sid: str, chat_service_sid: str):
    url = f"https://mcs.us1.twilio.com/v1/Services/{chat_service_sid}/Media/{media_sid}"
    auth = aiohttp.BasicAuth(login=account_sid, password=auth_token)

    async with aiohttp.ClientSession(auth=auth) as session:
        async with session.get(url) as response:
            if response.status == 200:
                return await response.text()  # or response.json() if the response is JSON
            else:
                return f"Error: {response.status}"
