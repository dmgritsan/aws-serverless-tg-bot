#!/usr/bin/env node
import * as cdk from 'aws-cdk-lib';
import { ServerlessTgBotStack } from '../lib/serverless-tg-bot-stack';

const app = new cdk.App();

// Get environment from context
const environment = process.env.NODE_ENV || 'dev';

// Check required environment variables during deployment
if (process.env.NODE_ENV !== 'bootstrap') {
  const requiredEnvVars = [
    'TELEGRAM_BOT_TOKEN',
  ];

  for (const envVar of requiredEnvVars) {
    if (!process.env[envVar]) {
      throw new Error(`${envVar} environment variable is required`);
    }
  }
}

// Create stack with environment-specific name
new ServerlessTgBotStack(app, `ServerlessTgBotStack-${environment}`, {
  env: { 
    account: process.env.CDK_DEFAULT_ACCOUNT, 
    region: process.env.CDK_DEFAULT_REGION 
  },
  environment: environment,
  stackName: `ServerlessTgBot-${environment}`,
});
