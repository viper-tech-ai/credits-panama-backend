import json
import logging
import re
from typing import Any, Optional
import aiohttp
import phonenumbers
import uuid
import mimetypes
from logger import async_logger

def find_dni(text):
    """
    Searches for a DNI number in the provided text.
    Expects the DNI format to be one of 'X-XXX-XXXX', 'X-XXX-XXX', 'N-XX-XXXX', or 'X-XX-XXXX' 
    where X is a digit and N is the letter 'N'.
    
    :param text: String to search in.
    :return: The found DNI number or None if no match is found.
    """
    # Regular expression pattern for DNI number
    # It matches 'X-XXX-XXXX', 'X-XXX-XXX', 'N-XX-XXXX', and 'X-XX-XXXX'
    pattern = r'\b(\d-\d{3}-\d{3,4}|N-\d{2}-\d{4})\b'

    # Search for the pattern in the text
    match = re.search(pattern, text)

    # Return the matched DNI number or None if no match is found
    return match.group(0) if match else None

def extract_numbers(whatsapp_number):
    # Parse the number using phonenumbers library
    try:
        number = phonenumbers.parse(whatsapp_number, None)
    except phonenumbers.NumberParseException as e:
        print(f"Error parsing number: {e}")
        return None

    if not phonenumbers.is_valid_number(number):
        print("Invalid phone number.")
        return None

    # Extract country code and national number
    country_code = number.country_code
    national_number = number.national_number

    return country_code, national_number

async def login(api_key) -> str:
    login_url = 'https://lab.creditspanama.com/api/v1/auth/'
    headers = {
        'Authorization': f'Bearer {api_key}'
    }
    async with aiohttp.ClientSession() as session:
        try:
            async with session.post(login_url, headers=headers) as response:
                data = await response.text()
                print('Server response:', data)
                data_json = json.loads(data)
                return data_json.get('session_auth')  # Extracting auth token
        except Exception as error:
            raise Exception(f'error: {error}')

async def get_user_info(auth_token, dni_number):
    get_user_info_url = "https://lab.creditspanama.com/api/v1/chat_bots/customer"
    headers = {
        "Authorization": f"Bearer {auth_token}",
        "Content-Type": "application/json"
    }
    payload = {
        "dni": dni_number
    }
    async with aiohttp.ClientSession() as session:
        try:
            async with session.post(get_user_info_url, json=payload, headers=headers) as response:
                data = await response.json()
                print(f"user info: {data}")
                # Process and return the relevant data as needed
                return data
        except Exception as error:
            return {"error-fatal": str(error)} 

async def convert_user_info_to_usable_format(provided_data: dict[str, Any]) -> dict[str, Any]:
    account_info = {
        "total_debt": provided_data['data']['answer1'],
        "remaining_payment_installments": provided_data['data']['answer2'],
        "next_payment_due_date": provided_data['data']['answer3'],
        "account_summary": provided_data['data']['answer4'],
        "cost_of_interest_in_usd": provided_data['data']['answer5'],
        "total_loan_including_interest": provided_data['data']['answer6'],
        "payment_frequency": provided_data['data']['answer7'],
        "account_status": provided_data['data']['answer8'],
        "total_paid_and_total_to_pay": provided_data['data']['answer13'],
        "first_payment_date": provided_data['data']['answer14'],
        "most_recent_payment": provided_data['data']['answer15'],
        "possibility_of_extension": provided_data['data']['answer16'],
        "user_next_payment_amount": provided_data['data']['answer18']
    }

    return account_info

async def get_user_context(dni_number: str, api_key: str) -> dict[str, Any]:
    auth = await login(api_key)
    provided_data = await get_user_info(auth, dni_number)

    if 'data' in provided_data:
        if 'error' in provided_data['data']:
            return {"msg": "Lo sentimos, no pudimos encontrar ese número de DNI. ¿Podrías verificar si es correcto?"}
        else:
            user_context = await convert_user_info_to_usable_format(provided_data)
    else:
        return {"msg": "Lo sentimos, algo salió mal de nuestra parte. Te derivaremos a un agente lo antes posible.", "msg-agent": "Hubo problemas para conectarse a la API cuando el usuario ingresó su número de DNI."}

    print(user_context)

    return user_context

async def fetch_and_upload_file(image_url: str, bucket_name: str, client, supabase_url) -> Optional[str]:
    async with aiohttp.ClientSession() as session:
        # Fetch the file asynchronously
        async with session.get(image_url) as response:
            if response.status == 200:
                file_content = await response.read()
                content_type = response.headers.get('Content-Type', 'application/octet-stream')
            else:
                async_logger.warn("Failed to fetch file from twilio, response: {response}")
                return None

    # Use the mimetypes module to guess the extension based on the MIME type
    guess_extension = mimetypes.guess_extension(content_type) or '.bin'
    random_filename = f"{uuid.uuid4()}{guess_extension}"

    # Upload the file to Supabase Storage with the random filename and MIME type
    response = await client.storage.from_(bucket_name).upload(random_filename, file_content, file_options={"content-type": content_type})
    print(f"Supabase Response: \n\n {response}")
    if response.status_code in (200, 201):
        url = f"{supabase_url}/storage/v1/object/public/{bucket_name}/{random_filename}"
        return url
    else:
        async_logger.warn("Failed to upload file to supabase: resoonse: {response}")

    return None
