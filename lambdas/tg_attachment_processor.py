import json
import boto3
import os
import urllib3
from botocore.exceptions import ClientError
import time
from common.telegram_utils import TelegramUtils

# Initialize clients
s3 = boto3.client('s3')
http = urllib3.PoolManager()
telegram_utils = TelegramUtils()

# Constants
MAX_RETRY_ATTEMPTS = int(os.environ.get('MAX_RETRY_ATTEMPTS', 3))
FILE_STORAGE_BUCKET = os.environ['FILE_STORAGE_BUCKET']
TELEGRAM_BOT_TOKEN = os.environ['TELEGRAM_BOT_TOKEN']
PROCESSING_QUEUE_URL = os.environ['PROCESSING_QUEUE_URL']

def get_file_extension(file_info):
    """Get file extension based on mime type or file path"""    
    # For photos, always use jpg
    if file_info.get('type') == 'photo':
        return '.jpg'
        
    mime_to_ext = {
        'image/jpeg': '.jpg',
        'image/png': '.png',
        'image/gif': '.gif',
        'video/mp4': '.mp4',
        'audio/mpeg': '.mp3',
        'audio/ogg': '.ogg',
        'application/pdf': '.pdf',
    }
    
    if 'mime_type' in file_info:
        return mime_to_ext.get(file_info['mime_type'], '')
    
    return ''

def get_file_from_telegram(file_id):
    """Get file path from Telegram"""
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/getFile"
    response = http.request(
        'GET',
        url,
        fields={'file_id': file_id}
    )
    
    if response.status != 200:
        raise Exception(f"Failed to get file path: {response.data.decode('utf-8')}")
    
    file_data = json.loads(response.data.decode('utf-8'))
    return file_data['result']['file_path']

def download_file(file_path):
    """Download file from Telegram"""
    url = f"https://api.telegram.org/file/bot{TELEGRAM_BOT_TOKEN}/{file_path}"
    response = http.request('GET', url)
    
    if response.status != 200:
        raise Exception(f"Failed to download file: {response.status}")
    
    return response.data

def upload_to_s3(chat_id, message_id, media_group_id, file_name, file_data):
    """Upload file to S3 with retry logic"""
    # Determine the folder structure based on media_group_id
    if media_group_id:
        key = f"{chat_id}/{media_group_id}/{message_id}/{file_name}"
    else:
        key = f"{chat_id}/no_media_group/{message_id}/{file_name}"
    
    for attempt in range(MAX_RETRY_ATTEMPTS):
        try:
            s3.put_object(
                Bucket=FILE_STORAGE_BUCKET,
                Key=key,
                Body=file_data
            )
            return key
        except Exception as e:
            if attempt == MAX_RETRY_ATTEMPTS - 1:
                raise e
            time.sleep(2 ** attempt)  # Exponential backoff
    
    return None

def process_file(data):
    """Process a single file"""
    file_info = data['file_info']
    file_id = file_info['file_id']
    
    # Get file name based on file type
    if file_info.get('file_name'):
        # Document type files have file_name directly
        file_name = file_info['file_name']
    elif 'file_unique_id' in file_info:
        # Photos and other media types need to use unique_id
        extension = get_file_extension(file_info)
        file_name = f"{file_info['file_unique_id']}{extension}"
    else:
        # Fallback name if no identifiers found
        file_name = f"file_{int(time.time())}"
    
    # Get file path from Telegram
    file_path = get_file_from_telegram(file_id)
    
    # Download file
    file_data = download_file(file_path)
    
    # Get media_group_id from data (might be None)
    media_group_id = data.get('media_group_id')
    
    # Upload to S3 with new path structure
    s3_key = upload_to_s3(
        chat_id=data['chat_id'],
        message_id=data['message_id'],
        media_group_id=media_group_id,
        file_name=file_name,
        file_data=file_data
    )
    
    return s3_key

def lambda_handler(event, context):
    for record in event['Records']:
        try:
            data = json.loads(record['body'])
            
            try:
                # Process the file
                s3_key = process_file(data)
                
                # Forward to processing queue with uploaded file info
                if s3_key:
                    data['uploaded_file'] = s3_key
                    telegram_utils.send_to_sqs(PROCESSING_QUEUE_URL, data)
                
            except Exception as e:
                telegram_utils.send_message(
                    data['chat_id'],
                    f"❌ Failed to process file: {str(e)}",
                    data['message_id']
                )
                raise e
                
        except Exception as e:
            print(f"Error processing message: {str(e)}")
            continue
    
    return {
        'statusCode': 200,
        'body': json.dumps('Processing complete')
    } 