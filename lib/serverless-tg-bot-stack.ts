import * as cdk from 'aws-cdk-lib';
import * as lambda from 'aws-cdk-lib/aws-lambda';
import * as dynamodb from 'aws-cdk-lib/aws-dynamodb';
import * as sqs from 'aws-cdk-lib/aws-sqs';
import * as iam from 'aws-cdk-lib/aws-iam';
import * as apigateway from 'aws-cdk-lib/aws-apigateway';
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

    // Create DynamoDB tables
    const messageLogsTable = new dynamodb.Table(this, `MessageLogs-${env}`, {
      partitionKey: { name: 'user_id', type: dynamodb.AttributeType.STRING },
      sortKey: { name: 'timestamp', type: dynamodb.AttributeType.STRING },
      billingMode: dynamodb.BillingMode.PAY_PER_REQUEST,
      timeToLiveAttribute: 'ttl',
      removalPolicy: cdk.RemovalPolicy.DESTROY,
    });

    // Create SQS queue for outgoing messages
    const outgoingQueue = new sqs.Queue(this, `OutgoingQueue-${env}`, {
      visibilityTimeout: cdk.Duration.seconds(30),
    });

    // Create Lambda functions
    const messageProcessor = new lambda.Function(this, 'TelegramMessageProcessor', {
      runtime: lambda.Runtime.PYTHON_3_12,
      handler: 'tg_message_processing.lambda_handler',
      code: lambda.Code.fromAsset(path.join(__dirname, '../lambdas'), {
        exclude: ['*', '!tg_message_processing.py'],
      }),
      role: new iam.Role(this, 'MessageProcessorRole', {
        assumedBy: new iam.ServicePrincipal('lambda.amazonaws.com'),
        managedPolicies: [
          iam.ManagedPolicy.fromAwsManagedPolicyName('service-role/AWSLambdaBasicExecutionRole'),
        ],
        inlinePolicies: {
          'DynamoDBAccess': new iam.PolicyDocument({
            statements: [
              new iam.PolicyStatement({
                effect: iam.Effect.ALLOW,
                actions: [
                  'dynamodb:PutItem',
                  'dynamodb:Query'
                ],
                resources: [messageLogsTable.tableArn]
              })
            ]
          }),
          'SQSAccess': new iam.PolicyDocument({
            statements: [
              new iam.PolicyStatement({
                effect: iam.Effect.ALLOW,
                actions: ['sqs:SendMessage'],
                resources: [outgoingQueue.queueArn]
              })
            ]
          })
        }
      }),
      timeout: cdk.Duration.seconds(30),
      environment: {
        OUTGOING_QUEUE_URL: outgoingQueue.queueUrl,
        MESSAGE_LOGS_TABLE: messageLogsTable.tableName,
        TELEGRAM_BOT_TOKEN: process.env.TELEGRAM_BOT_TOKEN || '',
      },
    });

    const messageSender = new lambda.Function(this, 'TelegramMessageSender', {
      runtime: lambda.Runtime.PYTHON_3_12,
      handler: 'tg_message_sender.lambda_handler',
      code: lambda.Code.fromAsset(path.join(__dirname, '../lambdas'), {
        exclude: ['*', '!tg_message_sender.py'],
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
    webhookResource.addMethod('POST', new apigateway.LambdaIntegration(messageProcessor));

    // Add output for webhook URL
    new cdk.CfnOutput(this, 'WebhookUrl', {
      value: `${api.url}tg-webhook`,
      description: 'URL for Telegram webhook',
    });
  }
} 