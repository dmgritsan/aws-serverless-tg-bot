import json
import boto3
import os
import datetime
from botocore.exceptions import ClientError

class TelegramUtils:
    def __init__(self):
        self.sqs = boto3.client('sqs')
        self.dynamodb = boto3.resource('dynamodb')
        self.outgoing_queue_url = os.environ['OUTGOING_QUEUE_URL']
        self.message_logs_table = self.dynamodb.Table(os.environ['MESSAGE_LOGS_TABLE'])
    
    def extract_file_info(self, message):
        """Extract file information from different types of attachments"""
        attachment_types = [
            ('photo', lambda x: x[-1]),  # Get the largest photo
            ('video', lambda x: x),
            ('document', lambda x: x),
            ('audio', lambda x: x),
            ('voice', lambda x: x),
        ]
        
        for att_type, processor in attachment_types:
            if att_type in message:
                file_data = processor(message[att_type])
                return {
                    'type': att_type,
                    'file_id': file_data.get('file_id'),
                    'file_unique_id': file_data.get('file_unique_id'),
                    'file_size': file_data.get('file_size'),
                    'mime_type': file_data.get('mime_type'),
                    'file_name': file_data.get('file_name'),
                    'media_group_id': message.get('media_group_id'),
                    'caption': message.get('caption'),
                }
        return None

    def extract_message_data(self, message_data, message_type='user_message'):
        """Extract all necessary data from Telegram message"""
        from_data = message_data.get('from', {})
        chat_data = message_data.get('chat', {})
        
        # Basic message data
        data = {
            'user_id': str(from_data.get('id')),
            'chat_id': str(chat_data.get('id')),
            'message_id': message_data.get('message_id'),
            'sender_id': str(from_data.get('id')),
            'is_bot': from_data.get('is_bot', False),
            'media_group_id': message_data.get('media_group_id'),
            'text': message_data.get('text', ''),
            'caption': message_data.get('caption', ''),
            'message_type': message_type
        }
        
        # Extract file info if present
        file_info = self.extract_file_info(message_data)
        if file_info:
            data['file_info'] = file_info
        
        return data

    def log_message(self, message_data, message_type='user_message'):
        """Log message to DynamoDB using Telegram message data"""
        data = self.extract_message_data(message_data, message_type)
        timestamp = datetime.datetime.now().isoformat()
        
        item = {
            'user_id': data['user_id'],
            'timestamp': timestamp,
            'message_type': data['message_type'],
            'message': data['caption'] if data['caption'] else data['text'],
            'telegram_message_id': data['message_id'],
            'chat_id': data['chat_id'],
            'sender_id': data['sender_id'],
            'is_bot': data['is_bot'],
            'media_group_id': data['media_group_id'],
            'ttl': int((datetime.datetime.now() + datetime.timedelta(days=90)).timestamp())
        }
        
        if 'file_info' in data:
            item['file_info'] = data['file_info']
        
        try:
            self.message_logs_table.put_item(Item=item)
        except ClientError as e:
            print(f"Error logging message: {e}")
    
    def send_to_sqs(self, queue_url, message_body):
        """Send message to SQS queue"""
        self.sqs.send_message(
            QueueUrl=queue_url, 
            MessageBody=json.dumps(message_body)
        )
    
    def send_message(self, chat_id, text, reply_to_message_id=None):
        """Send message to user through SQS outgoing queue"""
        outgoing_message = {
            'chat_id': chat_id, 
            'message': text,
            'reply_to_message_id': reply_to_message_id
        }
        
        # Log outgoing message
        log_message = {
            'from': {'id': 'bot', 'is_bot': True},
            'chat': {'id': chat_id},
            'message_id': reply_to_message_id,  # Using reply_to as reference
            'text': text
        }
        self.log_message(log_message, message_type='bot_message')
        
        # Send to outgoing queue
        self.send_to_sqs(self.outgoing_queue_url, outgoing_message) 