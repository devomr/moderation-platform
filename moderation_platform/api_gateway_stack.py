# Third party imports
from constructs import Construct
from aws_cdk import (
    Duration, RemovalPolicy, Fn, Stack, Tags, aws_apigateway, aws_cognito,
    aws_lambda, aws_logs, aws_iam, aws_cloudwatch, aws_cloudwatch_actions,
    aws_sns
)


class ApiGatewayStack(Stack):

    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # import existing resources
        user_pool = aws_cognito.UserPool.from_user_pool_arn(
            self,
            id='user-pool',
            user_pool_arn=Fn.import_value('ModerationPlatformUserPoolArn')
        )

        backend_monitoring_topic = aws_sns.Topic.from_topic_arn(
            self,
            id='backend-monitoring-topic',
            topic_arn=Fn.import_value('BackendMonitoringTopicArn')
        )

        generate_presigned_url_lambda = self.create_generate_presigned_url_lambda(
            monitoring_topic=backend_monitoring_topic
        )

        # create EDGE Rest API
        rest_api = aws_apigateway.RestApi(
            self,
            id='rest-api',
            rest_api_name='rest-api',
            default_cors_preflight_options=aws_apigateway.CorsOptions(
                allow_origins=aws_apigateway.Cors.ALL_ORIGINS,
                allow_methods=aws_apigateway.Cors.ALL_METHODS,
                allow_headers=[
                    'Content-Type',
                    'X-Amz-Date',
                    'Authorization',
                    'X-Api-Key',
                    'X-Amz-Security-Token',
                ],
                allow_credentials=True,
            ),
            endpoint_configuration=aws_apigateway.EndpointConfiguration(
                types=[aws_apigateway.EndpointType.EDGE]
            ),
        )

        authorizer = aws_apigateway.CognitoUserPoolsAuthorizer(
            self, id='cognito-authorizer', cognito_user_pools=[user_pool]
        )

        # add endpoint for generating the presigned URL used to upload files
        generate_presigned_url = rest_api.root.add_resource(
            path_part='generate_presigned_url'
        )
        generate_presigned_url.add_method(
            http_method='POST',
            integration=aws_apigateway
            .LambdaIntegration(generate_presigned_url_lambda),
            authorizer=authorizer,
            authorization_type=aws_apigateway.AuthorizationType.COGNITO,
        )

    def create_generate_presigned_url_lambda(
        self,
        monitoring_topic: aws_sns.ITopic,
    ) -> aws_lambda.Function:
        """Create Lambda function that generates presigned URLs for S3 uploads
        
        Args:
            monitoring_topic (aws_sns.ITopic): SNS topic used to send alarm notifications

        Returns:
            aws_lambda.Function: Lambda function
        """
        # Get the upload bucket ARN from CloudFormation exports
        upload_bucket_arn = Fn.import_value('UploadBucketArn')
        upload_bucket_name = upload_bucket_arn.split(':')[-1]

        lambda_function = aws_lambda.Function(
            self,
            id='generate-presigned-url-lambda',
            function_name='ModerationPlatform-generatePresignedUrl',
            description=
            'Lambda function that generates presigned URLs for S3 uploads',
            runtime=aws_lambda.Runtime.PYTHON_3_12,
            code=aws_lambda.Code
            .from_asset('moderation_platform/lambdas/generate_presigned_url'),
            handler='lambda_function.lambda_handler',
            memory_size=128,
            timeout=Duration.seconds(10),
            tracing=aws_lambda.Tracing.ACTIVE,
            environment={
                'UPLOAD_BUCKET': upload_bucket_name,
            },
        )

        lambda_alarm = aws_cloudwatch.Alarm(
            self,
            id='start-moderation-lambda-alarm',
            alarm_name=lambda_function.function_name,
            metric=aws_cloudwatch.Metric(
                metric_name='Errors',
                namespace='AWS/Lambda',
                dimensions_map={
                    'FunctionName': lambda_function.function_name,
                    'Resource': lambda_function.function_name
                },
                statistic='sum',
            ).with_(period=Duration.seconds(3600), statistic='sum'),
            threshold=1,
            evaluation_periods=1,
            alarm_description=(
                'CloudWatch alarm for Lambda function '
                f'{lambda_function.function_name}'
            ),
            comparison_operator=aws_cloudwatch.ComparisonOperator
            .GREATER_THAN_OR_EQUAL_TO_THRESHOLD,
            treat_missing_data=aws_cloudwatch.TreatMissingData.MISSING,
        )
        lambda_alarm.add_alarm_action(
            aws_cloudwatch_actions.SnsAction(monitoring_topic)
        )

        # Add permissions to generate presigned URLs for the upload bucket
        lambda_function.add_to_role_policy(
            aws_iam.PolicyStatement(
                actions=['s3:PutObject'], resources=[f"{upload_bucket_arn}/*"]
            )
        )

        aws_logs.LogGroup(
            self,
            id='generate-presigned-url-lambda-log-group',
            log_group_name=f'/aws/lambda/{lambda_function.function_name}',
            retention=aws_logs.RetentionDays.ONE_WEEK,
            removal_policy=RemovalPolicy.DESTROY,
        )

        Tags.of(lambda_function
               ).add('Name', 'ModerationPlatform-generatePresignedUrl')

        return lambda_function
