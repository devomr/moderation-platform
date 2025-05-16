# Moderation Platform

A content moderation platform built with AWS CDK that uses AWS services to detect and moderate inappropriate content.

- Diagrams added under the **docs** folder
- Workflow demo images added under the **docs/demo** folder

## Architecture

The platform consists of the following components:

- **S3 Stack**: Creates an S3 bucket for content uploads
- **Cognito Stack**: Creates Cognito user pool and app client used for authentication & authorization
- **ApiGateway Stack**: Creates REST API and Lambda function used to generate presigned URL
- **Observability Stack**: Creates SNS topics for monitoring and alerting
- **Moderation Stack**: Creates the core moderation workflows using Step Functions, Lambda, and AWS AI services
- **CI/CD Stack**: Creates a CI/CD pipeline for automated deployment from GitHub

## Future Development

- **Enable human moderation**: Enable human moderation in text & image moderation workflows by integrating Amazon Augumented AI
- **Text moderation for multiple languages**: Add possibility to moderate text in multiple languages (use Amazon Translate)
- **Add notifications**: Add possibility to notify people when inappropriate content is detected or is pending to be reviewd by human
- **Secure CloudFront distribution using WAF**: Add WAF to secure the CloudFront distribution that sits in front of API Gateway and S3
- **Improve Observability**: Add more metrics & alarms for critical components (moderation workflows, api requests etc),
  add CloudWatch dashboard to view important metrics
- **Improve CI/CD pipeline**: Add tests (unit, E2E), type checking, vulnerability scanning

## CI/CD Pipeline

The CI/CD pipeline automatically deploys the stacks when code is pushed to your GitHub repository. The pipeline consists of:

1. **Source Stage**: Triggered when code is pushed to the GitHub repository
2. **Build and Deploy Stage**: Builds and deploys the CDK stacks

## Getting Started

### Prerequisites

- AWS CLI configured with appropriate credentials
- Node.js and npm installed
- Python 3.12 or later installed
- AWS CDK installed (`npm install -g aws-cdk`)
- GitHub personal access token with repo scope

### Setup GitHub Integration

1. Create a GitHub personal access token with repo scope
2. Store the token in AWS Secrets Manager:

   ```
   aws secretsmanager create-secret --name github-token --secret-string YOUR_GITHUB_TOKEN
   ```

3. Update the `cdk.json` file with your GitHub repository information:
   ```json
   "ModerationPlatform": {
     "RepositoryName": "your-repo-name",
     "RepositoryOwner": "your-github-username",
     "BranchName": "main"
   }
   ```

### Installation

1. Deploy the CI/CD stack:

   ```
   cdk deploy CICDStack
   ```

2. Push your code to the GitHub repository to trigger the pipeline

### Configuration

Configuration is stored in `cdk.json` under the `ModerationPlatform` context key:

```json
"ModerationPlatform": {
  "AccountId": "your-account-id",
  "Region": "your-region",
  "HumanWorkflowArn": "your-human-workflow-arn",
  "RepositoryName": "your-repo-name",
  "RepositoryOwner": "your-github-username",
  "BranchName": "main"
}
```

## Usage

1. Upload content to the S3 bucket
2. The moderation workflow will automatically process the content
3. Results will be available through the Step Functions execution history

## Development

After making changes to the code:

1. Commit and push your changes to the GitHub repository
2. The CI/CD pipeline will automatically deploy the changes
