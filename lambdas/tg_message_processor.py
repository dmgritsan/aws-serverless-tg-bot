import json
import os
from common.telegram_utils import TelegramUtils
from typing import List, Dict
from dataclasses import dataclass
from datetime import datetime

# Initialize telegram utils
telegram_utils = TelegramUtils()

# TODO: In future, this should come from a database
CONTEXT_QUESTIONS = [
    "What is your motorbike? Answer with all the details that could help to identify it.",
    "What production year is your motorbike?",
    "What is the problem with your motorbike?"
]

ROLE_CONTEXT = """You are a friendly assistant conducting an initial user survey. 
Be polite and engaging while collecting information about the user."""

@dataclass
class ConversationMessage:
    role: str
    content: str
    timestamp: str

def get_conversation_history(user_id: str) -> List[ConversationMessage]:
    """Get conversation history from DynamoDB"""
    # Query the last N messages for this user
    response = telegram_utils.message_logs_table.query(
        KeyConditionExpression='user_id = :uid',
        ExpressionAttributeValues={':uid': user_id},
        ScanIndexForward=False,  # Most recent first
        Limit=100  # Adjust as needed
    )
    
    messages = []
    for item in response['Items']:
        role = 'assistant' if item['is_bot'] else 'user'
        messages.append(ConversationMessage(
            role=role,
            content=item['message'],
            timestamp=item['timestamp']
        ))
    
    return sorted(messages, key=lambda x: x.timestamp)

def prepare_ai_context(data: Dict, conversation_history: List[ConversationMessage]) -> Dict:
    """Prepare context for AI processor"""
    return {
        'role_context': ROLE_CONTEXT,
        'questions': CONTEXT_QUESTIONS,
        'conversation_history': [
            {
                'role': msg.role,
                'content': msg.content,
                'timestamp': msg.timestamp
            } for msg in conversation_history
        ],
        'outgoing_metadata': {
            'chat_id': data['chat_id'],
            'reply_to_message_id': data['message_id']
        },
        'outgoing_queue_url': os.environ['OUTGOING_QUEUE_URL']
    }

def lambda_handler(event, context):
    for record in event['Records']:
        try:
            data = json.loads(record['body'])
            
            # Handle messages with uploaded files
            if 'uploaded_file' in data:
                # Create test buttons
                buttons = [
                    [{'text': '✅ Confirm', 'callback_data': f'confirm_{data["message_id"]}'}],
                    [{'text': '❌ Delete', 'callback_data': f'delete_{data["message_id"]}'}]
                ]
                
                telegram_utils.send_message(
                    data['chat_id'],
                    f"✅ File has been uploaded successfully: {data['uploaded_file']}",
                    data['message_id'],
                    inline_buttons=buttons
                )
                continue
            
            # Handle text messages
            if data.get('text'):
                # Get conversation history
                conversation_history = get_conversation_history(data['user_id'])
                
                # Prepare context for AI processor
                ai_context = prepare_ai_context(data, conversation_history)
                
                # Send to AI queue
                telegram_utils.send_to_sqs(
                    os.environ['AI_QUEUE_URL'],
                    ai_context
                )
            
        except Exception as e:
            print(f"Error processing message: {str(e)}")
            print(f"Message data: {json.dumps(data)}")
            continue
    
    return {
        'statusCode': 200,
        'body': json.dumps('Processing complete')
    } 