import json
import boto3
import datetime
import os
import urllib3
from botocore.exceptions import ClientError
from urllib.parse import quote

# Initialize these as None
dynamodb = None
message_logs_table = None
sqs = None
outgoing_queue_url = None

# Initialize http client
http = urllib3.PoolManager()

def get_aws_resources():
    """Lazy initialization of AWS resources"""
    global dynamodb, message_logs_table, sqs, outgoing_queue_url
    
    if dynamodb is None:
        dynamodb = boto3.resource('dynamodb')
        message_logs_table = dynamodb.Table(os.environ['MESSAGE_LOGS_TABLE'])
        
    if sqs is None:
        sqs = boto3.client('sqs')
        outgoing_queue_url = os.environ['OUTGOING_QUEUE_URL']
    
    return dynamodb, message_logs_table, sqs, outgoing_queue_url

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

ERROR_MESSAGE = """
❌ Unknown command.

Please use:
/start - Show welcome message
/help - Show help message

Check out the project:
https://github.com/dmgritsan/aws-serverless-tg-bot
"""

def lambda_handler(event, context):
    # Get AWS resources at the start of handler
    global dynamodb, message_logs_table, sqs, outgoing_queue_url
    dynamodb, message_logs_table, sqs, outgoing_queue_url = get_aws_resources()
    
    try:
        body = json.loads(event.get('body', '{}'))
        message = body.get('message', {})
        
        # More explicit handling of missing user data
        from_data = message.get('from')
        if not from_data or 'id' not in from_data:
            print("Error: Invalid message format - missing user data")
            return {
                'statusCode': 400,
                'body': json.dumps({'error': 'Missing or invalid user data in request'})
            }
            
        user_id = str(from_data['id'])
        text = message.get('text', '')
        
        if not user_id:
            print("Error: No user_id found in request")
            return {
                'statusCode': 400,
                'body': json.dumps({'error': 'No user_id found in request'})
            }
        
        # Log all incoming messages
        log_message(user_id, text, message)
        
        # Handle commands
        if text == '/start':
            send_message(user_id, WELCOME_MESSAGE)
        elif text == '/help':
            send_message(user_id, HELP_MESSAGE)
        else:
            send_message(user_id, ERROR_MESSAGE)

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

def log_message(user_id, message_text, message_data):
    """Log message to DynamoDB using Telegram message data"""
    timestamp = datetime.datetime.now().isoformat()
    from_user = message_data.get('from', {})

    item = {
        'user_id': user_id,
        'timestamp': timestamp,
        'message_type': 'user_message',
        'message': message_text,
        'telegram_message_id': message_data.get('message_id'),
        'sender_id': str(from_user.get('id')),
        'is_bot': from_user.get('is_bot', False),
        'ttl': int((datetime.datetime.now() + datetime.timedelta(days=90)).timestamp())
    }
    try:
        message_logs_table.put_item(Item=item)
    except ClientError as e:
        print(f"Error logging message: {e}")

def send_to_sqs(queue_url, message_body):
    sqs.send_message(QueueUrl=queue_url, MessageBody=json.dumps(message_body))

def send_message(user_id, text):
    outgoing_message = {'user_id': user_id, 'message': text}
    send_to_sqs(outgoing_queue_url, outgoing_message)
