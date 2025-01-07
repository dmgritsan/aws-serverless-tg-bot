import * as cdk from 'aws-cdk-lib';
import * as lambda from 'aws-cdk-lib/aws-lambda';
import * as dynamodb from 'aws-cdk-lib/aws-dynamodb';
import * as sqs from 'aws-cdk-lib/aws-sqs';
import * as iam from 'aws-cdk-lib/aws-iam';
import * as apigateway from 'aws-cdk-lib/aws-apigateway';
import * as s3 from 'aws-cdk-lib/aws-s3';
import { Construct } from 'constructs';
import * as path from 'path';
import { SqsEventSource } from 'aws-cdk-lib/aws-lambda-event-sources';

export interface ServerlessTgBotStackProps extends cdk.StackProps {
  environment: string;
}

export class ServerlessTgBotStack extends cdk.Stack {
  constructor(scope: Construct, id: string, props: ServerlessTgBotStackProps) {
    super(scope, id, props);

    const env = props.environment;

    // Create SQS queues with proper configuration
    const outgoingQueue = new sqs.Queue(this, `OutgoingQueue-${env}`, {
      visibilityTimeout: cdk.Duration.seconds(30),
      retentionPeriod: cdk.Duration.days(1),
      removalPolicy: cdk.RemovalPolicy.DESTROY,
    });

    const processingQueue = new sqs.Queue(this, `ProcessingQueue-${env}`, {
      visibilityTimeout: cdk.Duration.seconds(30),
      retentionPeriod: cdk.Duration.days(1),
      removalPolicy: cdk.RemovalPolicy.DESTROY,
    });

    const uploadQueue = new sqs.Queue(this, `UploadQueue-${env}`, {
      visibilityTimeout: cdk.Duration.seconds(90),
      retentionPeriod: cdk.Duration.days(1),
      removalPolicy: cdk.RemovalPolicy.DESTROY,
    });

    const callbackQueue = new sqs.Queue(this, 'CallbackQueue', {
      queueName: `${id}-callback-queue-${env}`,
      visibilityTimeout: cdk.Duration.seconds(60),
      retentionPeriod: cdk.Duration.days(1),
    });

    // Create DynamoDB table with proper update behavior
    const messageLogsTable = new dynamodb.Table(this, `MessageLogs-${env}`, {
      partitionKey: { name: 'user_id', type: dynamodb.AttributeType.STRING },
      sortKey: { name: 'timestamp', type: dynamodb.AttributeType.STRING },
      timeToLiveAttribute: 'ttl',
      removalPolicy: cdk.RemovalPolicy.DESTROY,
      // Enable point-in-time recovery for safer updates
      pointInTimeRecovery: true,
    });

    // Add GSI for media groups
    messageLogsTable.addGlobalSecondaryIndex({
      indexName: 'MediaGroupIndex',
      partitionKey: { name: 'media_group_id', type: dynamodb.AttributeType.STRING },
      sortKey: { name: 'timestamp', type: dynamodb.AttributeType.STRING },
    });

    // Create S3 bucket for file storage
    const fileStorageBucket = new s3.Bucket(this, `FileStorage-${env}`, {
      removalPolicy: cdk.RemovalPolicy.DESTROY,
      // Remove autoDeleteObjects and handle cleanup differently
      lifecycleRules: [
        {
          // Automatically delete objects after 30 days
          expiration: cdk.Duration.days(30),
        }
      ],
      // Enable versioning for better data protection
      versioned: true,
      // Block public access
      blockPublicAccess: s3.BlockPublicAccess.BLOCK_ALL,
      // Enable encryption
      encryption: s3.BucketEncryption.S3_MANAGED,
    });

    // Create Lambda function for message validation
    const messageValidator = new lambda.Function(this, 'TelegramMessageValidator', {
      runtime: lambda.Runtime.PYTHON_3_12,
      handler: 'tg_message_validator.lambda_handler',
      code: lambda.Code.fromAsset(path.join(__dirname, '../lambdas'), {
        exclude: ['*.*', '!tg_message_validator.py', '!common/telegram_utils.py'],
      }),
      environment: {
        MESSAGE_LOGS_TABLE: messageLogsTable.tableName,
        OUTGOING_QUEUE_URL: outgoingQueue.queueUrl,
        PROCESSING_QUEUE_URL: processingQueue.queueUrl,
        UPLOAD_QUEUE_URL: uploadQueue.queueUrl,
        CALLBACK_QUEUE_URL: callbackQueue.queueUrl,
        TELEGRAM_BOT_TOKEN: process.env.TELEGRAM_BOT_TOKEN || '',
      },
      role: new iam.Role(this, 'MessageValidatorRole', {
        assumedBy: new iam.ServicePrincipal('lambda.amazonaws.com'),
        managedPolicies: [
          iam.ManagedPolicy.fromAwsManagedPolicyName('service-role/AWSLambdaBasicExecutionRole'),
        ],
        inlinePolicies: {
          'LambdaAccess': new iam.PolicyDocument({
            statements: [
              new iam.PolicyStatement({
                effect: iam.Effect.ALLOW,
                actions: [
                  'dynamodb:PutItem',
                  'dynamodb:Query',
                  'sqs:SendMessage',
                  'sqs:GetQueueUrl'
                ],
                resources: [
                  messageLogsTable.tableArn,
                  outgoingQueue.queueArn,
                  processingQueue.queueArn,
                  uploadQueue.queueArn,
                  callbackQueue.queueArn
                ]
              })
            ]
          })
        }
      }),
      timeout: cdk.Duration.seconds(30),
    });

    // Create Lambda function for message processing
    const messageProcessor = new lambda.Function(this, 'TelegramMessageProcessor', {
      runtime: lambda.Runtime.PYTHON_3_12,
      handler: 'tg_message_processor.lambda_handler',
      code: lambda.Code.fromAsset(path.join(__dirname, '../lambdas'), {
        exclude: ['*.*', '!tg_message_processor.py', '!common/telegram_utils.py'],
      }),
      environment: {
        MESSAGE_LOGS_TABLE: messageLogsTable.tableName,
        OUTGOING_QUEUE_URL: outgoingQueue.queueUrl,
        UPLOAD_QUEUE_URL: uploadQueue.queueUrl,
      },
      role: new iam.Role(this, 'MessageProcessorRole', {
        assumedBy: new iam.ServicePrincipal('lambda.amazonaws.com'),
        managedPolicies: [
          iam.ManagedPolicy.fromAwsManagedPolicyName('service-role/AWSLambdaBasicExecutionRole'),
        ],
        inlinePolicies: {
          'LambdaAccess': new iam.PolicyDocument({
            statements: [
              new iam.PolicyStatement({
                effect: iam.Effect.ALLOW,
                actions: [
                  'dynamodb:PutItem',
                  'dynamodb:Query',
                  'sqs:SendMessage',
                  'sqs:GetQueueUrl',
                  'sqs:ReceiveMessage',
                  'sqs:DeleteMessage'
                ],
                resources: [
                  messageLogsTable.tableArn,
                  `${messageLogsTable.tableArn}/index/MediaGroupIndex`,
                  outgoingQueue.queueArn,
                  uploadQueue.queueArn,
                  processingQueue.queueArn
                ]
              })
            ]
          })
        }
      }),
      timeout: cdk.Duration.seconds(30),
    });

    // Add SQS trigger for Message Processor
    messageProcessor.addEventSource(new SqsEventSource(processingQueue, {
      batchSize: 1,
    }));

    const messageSender = new lambda.Function(this, 'TelegramMessageSender', {
      runtime: lambda.Runtime.PYTHON_3_12,
      handler: 'tg_message_sender.lambda_handler',
      code: lambda.Code.fromAsset(path.join(__dirname, '../lambdas'), {
        exclude: ['*.*', '!tg_message_sender.py', '!common/telegram_utils.py'],
      }),
      role: new iam.Role(this, 'MessageSenderRole', {
        assumedBy: new iam.ServicePrincipal('lambda.amazonaws.com'),
        managedPolicies: [
          iam.ManagedPolicy.fromAwsManagedPolicyName('service-role/AWSLambdaBasicExecutionRole'),
        ],
        inlinePolicies: {
          'DynamoDBAccess': new iam.PolicyDocument({
            statements: [
              new iam.PolicyStatement({
                effect: iam.Effect.ALLOW,
                actions: ['dynamodb:PutItem'],
                resources: [messageLogsTable.tableArn]
              })
            ]
          })
        }
      }),
      timeout: cdk.Duration.seconds(30),
      environment: {
        MESSAGE_LOGS_TABLE: messageLogsTable.tableName,
        TELEGRAM_BOT_TOKEN: process.env.TELEGRAM_BOT_TOKEN || '',
      },
    });

    // Add SQS trigger for Message Sender
    messageSender.addEventSource(new SqsEventSource(outgoingQueue, {
      batchSize: 1,
    }));

    // Create Lambda function for attachment processing
    const attachmentProcessor = new lambda.Function(this, 'TelegramAttachmentProcessor', {
      runtime: lambda.Runtime.PYTHON_3_12,
      handler: 'tg_attachment_processor.lambda_handler',
      code: lambda.Code.fromAsset(path.join(__dirname, '../lambdas'), {
        exclude: ['*.*', '!tg_attachment_processor.py', '!common/telegram_utils.py'],
      }),
      environment: {
        FILE_STORAGE_BUCKET: fileStorageBucket.bucketName,
        PROCESSING_QUEUE_URL: processingQueue.queueUrl,
        OUTGOING_QUEUE_URL: outgoingQueue.queueUrl,
        TELEGRAM_BOT_TOKEN: process.env.TELEGRAM_BOT_TOKEN || '',
        MAX_RETRY_ATTEMPTS: '3',
      },
      role: new iam.Role(this, 'AttachmentProcessorRole', {
        assumedBy: new iam.ServicePrincipal('lambda.amazonaws.com'),
        managedPolicies: [
          iam.ManagedPolicy.fromAwsManagedPolicyName('service-role/AWSLambdaBasicExecutionRole'),
        ],
        inlinePolicies: {
          'LambdaAccess': new iam.PolicyDocument({
            statements: [
              new iam.PolicyStatement({
                effect: iam.Effect.ALLOW,
                actions: [
                  's3:PutObject',
                  's3:GetObject',
                  'sqs:SendMessage',
                  'sqs:GetQueueUrl'
                ],
                resources: [
                  `${fileStorageBucket.bucketArn}/*`,
                  processingQueue.queueArn,
                  outgoingQueue.queueArn
                ]
              })
            ]
          })
        }
      }),
      timeout: cdk.Duration.seconds(60),
      memorySize: 256,
    });

    // Add SQS trigger for Attachment Processor
    attachmentProcessor.addEventSource(new SqsEventSource(uploadQueue, {
      batchSize: 1,
    }));

    // Create Lambda function for callback processing
    const callbackProcessor = new lambda.Function(this, 'TelegramCallbackProcessor', {
      runtime: lambda.Runtime.PYTHON_3_12,
      handler: 'tg_callback_processor.lambda_handler',
      code: lambda.Code.fromAsset(path.join(__dirname, '../lambdas'), {
        exclude: ['*.*', '!tg_callback_processor.py', '!common/telegram_utils.py'],
      }),
      environment: {
        OUTGOING_QUEUE_URL: outgoingQueue.queueUrl,
        TELEGRAM_BOT_TOKEN: process.env.TELEGRAM_BOT_TOKEN || '',
      },
      role: new iam.Role(this, 'CallbackProcessorRole', {
        assumedBy: new iam.ServicePrincipal('lambda.amazonaws.com'),
        managedPolicies: [
          iam.ManagedPolicy.fromAwsManagedPolicyName('service-role/AWSLambdaBasicExecutionRole'),
        ],
        inlinePolicies: {
          'LambdaAccess': new iam.PolicyDocument({
            statements: [
              new iam.PolicyStatement({
                effect: iam.Effect.ALLOW,
                actions: [
                  'sqs:SendMessage',
                  'sqs:GetQueueUrl'
                ],
                resources: [
                  outgoingQueue.queueArn
                ]
              })
            ]
          })
        }
      }),
      timeout: cdk.Duration.seconds(30),
    });

    // Add SQS trigger for Callback Processor
    callbackProcessor.addEventSource(new SqsEventSource(callbackQueue, {
      batchSize: 1,
    }));

    // Create API Gateway
    const api = new apigateway.RestApi(this, 'ServerlessTgBotApi', {
      restApiName: `Serverless Telegram Bot API - ${env}`,
      description: `API Gateway for Telegram Bot - ${env}`,
      deployOptions: {
        stageName: env,
        dataTraceEnabled: env === 'dev',
        loggingLevel: env === 'dev' 
          ? apigateway.MethodLoggingLevel.INFO 
          : apigateway.MethodLoggingLevel.ERROR,
        tracingEnabled: true,
      },
    });

    // Add Telegram webhook endpoint
    const webhookResource = api.root.addResource('tg-webhook');
    webhookResource.addMethod('POST', new apigateway.LambdaIntegration(messageValidator));

    // Add output for webhook URL
    new cdk.CfnOutput(this, 'WebhookUrl', {
      value: `${api.url}tg-webhook`,
      description: 'URL for Telegram webhook',
    });
  }
} 