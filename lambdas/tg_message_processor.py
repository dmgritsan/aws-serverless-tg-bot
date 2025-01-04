import json
import os
from common.telegram_utils import TelegramUtils

# Initialize telegram utils
telegram_utils = TelegramUtils()

ERROR_MESSAGE = """
❌ Unknown command.

Please use:
/start - Show welcome message
/help - Show help message

Check out the project:
https://github.com/dmgritsan/aws-serverless-tg-bot
"""

def lambda_handler(event, context):
    for record in event['Records']:
        try:
            data = json.loads(record['body'])
            
            # Handle messages with uploaded files
            if 'uploaded_file' in data:
                telegram_utils.send_message(
                    data['chat_id'],
                    f"✅ File has been uploaded successfully: {data['uploaded_file']}",
                    data['message_id']
                )
                continue
            
            # Handle text messages
            if data.get('text'):
                # Here you can add your text processing logic
                # For now, just send error message for unknown commands
                telegram_utils.send_message(data['chat_id'], ERROR_MESSAGE, data['message_id'])
            
        except Exception as e:
            print(f"Error processing message: {str(e)}")
            continue
    
    return {
        'statusCode': 200,
        'body': json.dumps('Processing complete')
    } 