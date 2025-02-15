import json
import os
import openai
from typing import List, Dict, Optional
from dataclasses import dataclass
import boto3

# Initialize OpenAI client
client = openai.OpenAI(api_key=os.environ['OPENAI_API_KEY'])

# Global constants
GPT_MODEL = "gpt-4o"

@dataclass
class ConversationMessage:
    role: str  # 'user' or 'assistant'
    content: str
    timestamp: str

@dataclass
class AIContext:
    role_context: str
    questions: List[str]
    conversation_history: List[ConversationMessage]
    outgoing_metadata: Dict
    outgoing_queue_url: str

def parse_ai_context(data: Dict) -> AIContext:
    """Parse incoming SQS message into AIContext"""
    return AIContext(
        role_context=data['role_context'],
        questions=data['questions'],
        conversation_history=[
            ConversationMessage(**msg) for msg in data['conversation_history']
        ],
        outgoing_metadata=data['outgoing_metadata'],
        outgoing_queue_url=data['outgoing_queue_url']
    )

def find_unanswered_questions(context: AIContext) -> List[str]:
    """
    Analyze conversation history to find unanswered questions
    Returns list of questions that haven't been clearly answered
    """
    system_prompt = f"""
    You are an AI assistant analyzing a conversation. Your task is to determine which questions 
    from the list have not been clearly answered yet. Context: {context.role_context}
    
    Questions to check:
    {json.dumps(context.questions, indent=2)}
    
    Conversation history:
    {json.dumps([{'role': msg.role, 'content': msg.content} for msg in context.conversation_history], indent=2)}
    
    Return a JSON array of questions that still need answers. If all questions are answered, return an empty array.
    """

    response = client.chat.completions.create(
        model=GPT_MODEL,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": "Analyze the conversation and list unanswered questions"}
        ],
        response_format={ "type": "json_object" }
    )
    
    result = json.loads(response.choices[0].message.content)
    return result.get('unanswered_questions', [])

def generate_next_question(context: AIContext, unanswered: List[str]) -> str:
    """Generate the next question to ask based on conversation context"""
    system_prompt = f"""
    You are an AI assistant with this role: {context.role_context}
    
    Your task is to ask the next question from this list in a natural, conversational way:
    {json.dumps(unanswered, indent=2)}
    
    Previous conversation:
    {json.dumps([{'role': msg.role, 'content': msg.content} for msg in context.conversation_history], indent=2)}
    
    Generate a friendly, contextual way to ask the next question.
    """

    response = client.chat.completions.create(
        model=GPT_MODEL,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": "Generate the next question"}
        ]
    )
    
    return response.choices[0].message.content

def generate_summary(context: AIContext) -> str:
    """Generate a summary when all questions are answered"""
    system_prompt = f"""
    You are an AI assistant with this role: {context.role_context}
    
    All questions have been answered. Generate a summary of the conversation addressing these points:
    {json.dumps(context.questions, indent=2)}
    
    Conversation history:
    {json.dumps([{'role': msg.role, 'content': msg.content} for msg in context.conversation_history], indent=2)}
    
    Provide a concise but comprehensive summary.
    """

    response = client.chat.completions.create(
        model=GPT_MODEL,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": "Generate summary"}
        ]
    )
    
    return response.choices[0].message.content

def send_message(sqs, message: str, metadata: Dict, queue_url: str):
    """Send message back to user via SQS"""
    message_body = {
        **metadata,
        'message': message
    }
    
    sqs.send_message(
        QueueUrl=queue_url,
        MessageBody=json.dumps(message_body)
    )

def lambda_handler(event, context):
    sqs = boto3.client('sqs')
    
    for record in event['Records']:
        try:
            # Parse incoming message
            data = json.loads(record['body'])
            ai_context = parse_ai_context(data)
            
            # Find unanswered questions
            unanswered = find_unanswered_questions(ai_context)
            
            if unanswered:
                # Generate next question
                next_question = generate_next_question(ai_context, unanswered)
                send_message(
                    sqs,
                    next_question,
                    ai_context.outgoing_metadata,
                    ai_context.outgoing_queue_url
                )
            else:
                # Generate summary
                summary = generate_summary(ai_context)
                send_message(
                    sqs,
                    summary,
                    ai_context.outgoing_metadata,
                    ai_context.outgoing_queue_url
                )
                
        except Exception as e:
            print(f"Error processing message: {str(e)}")
            print(f"Message data: {json.dumps(data)}")
            continue
    
    return {
        'statusCode': 200,
        'body': json.dumps('Processing complete')
    } 