import json
import os
import urllib3
from common.telegram_utils import TelegramUtils

# Initialize clients
http = urllib3.PoolManager()
telegram_utils = TelegramUtils(require_outgoing_queue=False)

# Constants
TELEGRAM_BOT_TOKEN = os.environ['TELEGRAM_BOT_TOKEN']

def send_telegram_message(chat_id, message, reply_to_message_id=None):
    """Send message to Telegram"""
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    
    data = {
        'chat_id': chat_id,
        'text': message,
        'parse_mode': 'HTML'
    }
    
    if reply_to_message_id:
        data['reply_to_message_id'] = reply_to_message_id
    
    response = http.request(
        'POST',
        url,
        fields=data
    )
    
    if response.status != 200:
        raise Exception(f"Failed to send message: {response.data.decode('utf-8')}")
    
    return json.loads(response.data.decode('utf-8'))

def lambda_handler(event, context):
    for record in event['Records']:
        try:
            message = json.loads(record['body'])
            chat_id = message['chat_id']
            text = message['message']
            reply_to = message.get('reply_to_message_id')
            
            # Send message to Telegram
            response = send_telegram_message(chat_id, text, reply_to)
            
            # Log the sent message using the response data
            telegram_utils.log_message(response['result'], message_type='bot_message')
            
        except Exception as e:
            print(f"Error sending message: {str(e)}")
            print(f"Message data: {json.dumps(message)}")
            continue
    
    return {
        'statusCode': 200,
        'body': json.dumps('Message sending complete')
    } 