import json
import os
import urllib3
from common.telegram_utils import TelegramUtils

# Initialize clients
http = urllib3.PoolManager()
telegram_utils = TelegramUtils()

def answer_callback_query(callback_id, text=None):
    """Answer callback query to remove loading state"""
    url = f"https://api.telegram.org/bot{os.environ['TELEGRAM_BOT_TOKEN']}/answerCallbackQuery"
    
    data = {'callback_query_id': callback_id}
    if text:
        data['text'] = text
        
    response = http.request('POST', url, fields=data)
    if response.status != 200:
        raise Exception(f"Failed to answer callback query: {response.data.decode('utf-8')}")

def lambda_handler(event, context):
    for record in event['Records']:
        try:
            data = json.loads(record['body'])
            callback_id = data['callback_id']
            chat_id = data['chat_id']
            message_id = data['message_id']
            callback_data = data['data']
            user_id = data['user_id']
            
            # Process callback data and send appropriate response
            if callback_data.startswith('confirm_'):
                answer_callback_query(callback_id, "✅ File confirmed!")
                telegram_utils.send_message(chat_id, "Thank you for confirming the file!")
            elif callback_data.startswith('delete_'):
                answer_callback_query(callback_id, "❌ File marked for deletion")
                telegram_utils.send_message(chat_id, "File will be deleted (not implemented yet)")
            else:
                answer_callback_query(callback_id, "Unknown action")
            
        except Exception as e:
            print(f"Error processing callback: {str(e)}")
            print(f"Callback data: {json.dumps(data)}")
            continue
    
    return {
        'statusCode': 200,
        'body': json.dumps('Callback processing complete')
    } 