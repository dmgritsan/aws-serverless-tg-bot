import json
import boto3
import urllib3
import os
import datetime
from botocore.exceptions import ClientError

# Initialize urllib3
http = urllib3.PoolManager()

# DynamoDB client
dynamodb = boto3.resource('dynamodb')
message_logs_table = dynamodb.Table(os.environ['MESSAGE_LOGS_TABLE'])

def log_bot_message(user_id, message_text, telegram_response):
    """Log bot's message to DynamoDB using Telegram response data"""
    timestamp = datetime.datetime.now().isoformat()
    result = telegram_response['result']
    from_user = result.get('from', {})  # Bot info from Telegram

    item = {
        'user_id': user_id,
        'timestamp': timestamp,
        'message_type': 'bot_message',
        'message': message_text,
        'telegram_message_id': result.get('message_id'),
        'sender_id': str(from_user.get('id')),
        'is_bot': from_user.get('is_bot', True),
        'ttl': int((datetime.datetime.now() + datetime.timedelta(days=90)).timestamp())
    }
    try:
        message_logs_table.put_item(Item=item)
    except ClientError as e:
        print(f"Error logging message: {e}")

def lambda_handler(event, context):
    for record in event['Records']:
        try:
            message = json.loads(record['body'])
            user_id = message['user_id']
            text = message['message']
            
            # Send message to Telegram
            response = http.request(
                'POST',
                f"https://api.telegram.org/bot{os.environ['TELEGRAM_BOT_TOKEN']}/sendMessage",
                headers={'Content-Type': 'application/json'},
                body=json.dumps({
                    'chat_id': user_id,
                    'text': text,
                    'parse_mode': 'HTML'
                })
            )
            
            if response.status == 200:
                telegram_response = json.loads(response.data.decode('utf-8'))
                log_bot_message(user_id, text, telegram_response)
            else:
                print(f"Failed to send message: {response.data.decode('utf-8')}")
                
        except Exception as e:
            print(f"Error processing message: {str(e)}")
            continue
    
    return {
        'statusCode': 200,
        'body': json.dumps('Messages processed')
    } 