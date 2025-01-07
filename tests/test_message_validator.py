import os
import json
import pytest
import boto3
from moto import mock_aws
from tg_message_validator import lambda_handler

# Test data
TEXT_MESSAGE = {
    'body': json.dumps({
        'message': {
            'message_id': 123,
            'from': {'id': 456, 'is_bot': False},
            'chat': {'id': 789},
            'text': 'Hello, world!'
        }
    })
}

PHOTO_MESSAGE = {
    'body': json.dumps({
        'message': {
            'message_id': 124,
            'from': {'id': 456, 'is_bot': False},
            'chat': {'id': 789},
            'photo': [
                {'file_id': 'small', 'file_unique_id': 'small_unique', 'file_size': 1024},
                {'file_id': 'large', 'file_unique_id': 'large_unique', 'file_size': 2048}
            ],
            'caption': 'Test photo'
        }
    })
}

DOCUMENT_MESSAGE = {
    'body': json.dumps({
        'message': {
            'message_id': 125,
            'from': {'id': 456, 'is_bot': False},
            'chat': {'id': 789},
            'document': {
                'file_id': 'doc123',
                'file_unique_id': 'doc_unique',
                'file_name': 'test.pdf',
                'mime_type': 'application/pdf',
                'file_size': 1024
            }
        }
    })
}

CALLBACK_QUERY = {
    'body': json.dumps({
        'callback_query': {
            'id': 'callback123',
            'from': {'id': 456, 'is_bot': False},
            'message': {
                'message_id': 126,
                'chat': {'id': 789},
                'text': 'Original message'
            },
            'data': 'test_callback'
        }
    })
}

@pytest.fixture
def aws_credentials():
    """Mocked AWS Credentials for moto"""
    os.environ['AWS_ACCESS_KEY_ID'] = 'testing'
    os.environ['AWS_SECRET_ACCESS_KEY'] = 'testing'
    os.environ['AWS_SECURITY_TOKEN'] = 'testing'
    os.environ['AWS_SESSION_TOKEN'] = 'testing'
    os.environ['AWS_DEFAULT_REGION'] = 'us-east-1'
    os.environ['TELEGRAM_BOT_TOKEN'] = 'test_token'

@pytest.fixture
def dynamodb(aws_credentials):
    with mock_aws():
        dynamodb = boto3.resource('dynamodb')
        
        # Create message logs table
        table = dynamodb.create_table(
            TableName='test-message-logs',
            KeySchema=[
                {'AttributeName': 'user_id', 'KeyType': 'HASH'},
                {'AttributeName': 'timestamp', 'KeyType': 'RANGE'}
            ],
            AttributeDefinitions=[
                {'AttributeName': 'user_id', 'AttributeType': 'S'},
                {'AttributeName': 'timestamp', 'AttributeType': 'S'},
                {'AttributeName': 'media_group_id', 'AttributeType': 'S'}
            ],
            GlobalSecondaryIndexes=[{
                'IndexName': 'MediaGroupIndex',
                'KeySchema': [
                    {'AttributeName': 'media_group_id', 'KeyType': 'HASH'},
                    {'AttributeName': 'timestamp', 'KeyType': 'RANGE'}
                ],
                'Projection': {'ProjectionType': 'ALL'}
            }],
            BillingMode='PAY_PER_REQUEST'
        )
        
        os.environ['MESSAGE_LOGS_TABLE'] = table.name
        yield dynamodb

@pytest.fixture
def sqs(aws_credentials):
    with mock_aws():
        sqs = boto3.client('sqs')
        
        # Create required queues
        queues = {
            'processing': sqs.create_queue(QueueName='test-processing-queue'),
            'upload': sqs.create_queue(QueueName='test-upload-queue'),
            'callback': sqs.create_queue(QueueName='test-callback-queue'),
            'outgoing': sqs.create_queue(QueueName='test-outgoing-queue')
        }
        
        # Set environment variables
        os.environ['PROCESSING_QUEUE_URL'] = queues['processing']['QueueUrl']
        os.environ['UPLOAD_QUEUE_URL'] = queues['upload']['QueueUrl']
        os.environ['CALLBACK_QUEUE_URL'] = queues['callback']['QueueUrl']
        os.environ['OUTGOING_QUEUE_URL'] = queues['outgoing']['QueueUrl']
        
        yield sqs

def get_sqs_messages(sqs, queue_url):
    """Helper to get messages from SQS queue"""
    response = sqs.receive_message(
        QueueUrl=queue_url,
        MaxNumberOfMessages=10
    )
    return [json.loads(msg['Body']) for msg in response.get('Messages', [])]

def test_text_message(dynamodb, sqs):
    # Process text message
    response = lambda_handler(TEXT_MESSAGE, None)
    assert response['statusCode'] == 200
    
    # Check DynamoDB entry
    table = dynamodb.Table(os.environ['MESSAGE_LOGS_TABLE'])
    items = table.scan()['Items']
    assert len(items) == 1
    assert items[0]['user_id'] == '456'
    assert items[0]['message'] == 'Hello, world!'
    
    # Check SQS message
    messages = get_sqs_messages(sqs, os.environ['PROCESSING_QUEUE_URL'])
    assert len(messages) == 1
    assert messages[0]['text'] == 'Hello, world!'

def test_photo_message(dynamodb, sqs):
    response = lambda_handler(PHOTO_MESSAGE, None)
    assert response['statusCode'] == 200
    
    # Check DynamoDB entry
    table = dynamodb.Table(os.environ['MESSAGE_LOGS_TABLE'])
    items = table.scan()['Items']
    assert len(items) == 1
    assert items[0]['file_info']['type'] == 'photo'
    assert items[0]['file_info']['file_id'] == 'large'
    
    # Check SQS message in upload queue
    messages = get_sqs_messages(sqs, os.environ['UPLOAD_QUEUE_URL'])
    assert len(messages) == 1
    assert messages[0]['file_info']['type'] == 'photo'

def test_document_message(dynamodb, sqs):
    response = lambda_handler(DOCUMENT_MESSAGE, None)
    assert response['statusCode'] == 200
    
    # Check DynamoDB entry
    table = dynamodb.Table(os.environ['MESSAGE_LOGS_TABLE'])
    items = table.scan()['Items']
    print(items)
    assert len(items) == 1
    assert items[0]['file_info']['type'] == 'document'
    assert items[0]['file_info']['file_name'] == 'test.pdf'
    
    # Check SQS message
    messages = get_sqs_messages(sqs, os.environ['UPLOAD_QUEUE_URL'])
    assert len(messages) == 1
    assert messages[0]['file_info']['mime_type'] == 'application/pdf'

def test_callback_query(dynamodb, sqs):
    response = lambda_handler(CALLBACK_QUERY, None)
    assert response['statusCode'] == 200
    
    # Check SQS message
    messages = get_sqs_messages(sqs, os.environ['CALLBACK_QUEUE_URL'])
    assert len(messages) == 1
    assert messages[0]['callback_id'] == 'callback123'
    assert messages[0]['data'] == 'test_callback' 