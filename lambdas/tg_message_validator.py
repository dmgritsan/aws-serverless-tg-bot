import json
import boto3
import os
from botocore.exceptions import ClientError
from common.telegram_utils import TelegramUtils

# Initialize these as None
dynamodb = None
message_logs_table = None
sqs = None
processing_queue_url = None
upload_queue_url = None
telegram_utils = None

WELCOME_MESSAGE = """
👋 Welcome to AWS Serverless TG Bot Demo!

This is a demonstration of a serverless Telegram bot built with AWS services.
Check out the project on GitHub: https://github.com/dmgritsan/aws-serverless-tg-bot

Commands:
/start - Show this welcome message
/help - Show usage instructions
"""

HELP_MESSAGE = """
ℹ️ AWS Serverless TG Bot Demo

This is a demo bot showing how to build serverless Telegram bots using:
• AWS Lambda
• API Gateway
• SQS
• DynamoDB

Source code and documentation:
https://github.com/dmgritsan/aws-serverless-tg-bot

Available commands:
/start - Show welcome message
/help - Show this help message
"""

def get_aws_resources():
    """Lazy initialization of AWS resources"""
    global dynamodb, message_logs_table, sqs, processing_queue_url, upload_queue_url, telegram_utils
    
    if dynamodb is None:
        dynamodb = boto3.resource('dynamodb')
        message_logs_table = dynamodb.Table(os.environ['MESSAGE_LOGS_TABLE'])
    
    if sqs is None:
        sqs = boto3.client('sqs')
        processing_queue_url = os.environ['PROCESSING_QUEUE_URL']
        upload_queue_url = os.environ['UPLOAD_QUEUE_URL']
    
    if telegram_utils is None:
        telegram_utils = TelegramUtils()
    
    return dynamodb, message_logs_table, sqs, processing_queue_url, upload_queue_url, telegram_utils

def is_first_media_group_message(media_group_id):
    if not media_group_id:
        return True
    """Check if this is the first message with this media_group_id"""
    try:
        response = message_logs_table.query(
            IndexName='MediaGroupIndex',
            KeyConditionExpression='media_group_id = :mgid',
            ExpressionAttributeValues={
                ':mgid': media_group_id
            },
            Limit=1  # We only need to know if there's more than one
        )
        return len(response.get('Items', [])) == 0
    except ClientError as e:
        print(f"Error querying media group: {e}")
        return False

def lambda_handler(event, context):
    # Get AWS resources at the start of handler
    global dynamodb, message_logs_table, sqs, processing_queue_url, upload_queue_url, telegram_utils
    dynamodb, message_logs_table, sqs, processing_queue_url, upload_queue_url, telegram_utils = get_aws_resources()
    
    try:
        body = json.loads(event.get('body', '{}'))
        message = body.get('message', {})
        
        # Extract and validate message data
        data = telegram_utils.extract_message_data(message)
        if not data['user_id'] or not data['chat_id']:
            print("Error: Invalid message format - missing user or chat data")
            return {
                'statusCode': 400,
                'body': json.dumps({'error': 'Missing or invalid user/chat data in request'})
            }
        
        first_media_group_message = is_first_media_group_message(data['media_group_id'])
        # Log message
        telegram_utils.log_message(message)
        
        # Handle basic commands directly
        if data['text'] == '/start':
            telegram_utils.send_message(data['chat_id'], WELCOME_MESSAGE, data['message_id'])
            return {'statusCode': 200, 'body': json.dumps({'status': 'ok'})}
            
        elif data['text'] == '/help':
            telegram_utils.send_message(data['chat_id'], HELP_MESSAGE, data['message_id'])
            return {'statusCode': 200, 'body': json.dumps({'status': 'ok'})}
        
        # Route message based on content
        if 'file_info' in data:
            # Send to upload queue
            telegram_utils.send_to_sqs(upload_queue_url, data)
            
            # Only send notification for first message in media group
            if first_media_group_message:
                telegram_utils.send_message(data['chat_id'], "📤 Processing your file...", data['message_id'])
        else:
            # Text-only message goes to processing queue
            telegram_utils.send_to_sqs(processing_queue_url, data)
        
        return {
            'statusCode': 200,
            'body': json.dumps({'status': 'ok'})
        }

    except Exception as e:
        print(f"Error processing webhook: {str(e)}")
        print(f"Event: {json.dumps(event)}")
        return {
            'statusCode': 500,
            'body': json.dumps({'error': str(e)})
        } 