# Third party imports
from constructs import Construct
from aws_cdk import (
    Duration,
    CfnOutput,
    Fn,
    RemovalPolicy,
    Stack,
    Tags,
    aws_s3,
    aws_sqs,
    aws_sns,
    aws_s3_notifications,
    aws_cloudwatch,
    aws_cloudwatch_actions,
    aws_lambda,
    aws_lambda_event_sources,
    aws_stepfunctions,
    aws_stepfunctions_tasks,
    aws_logs,
    aws_iam,
)

# Local imports
from moderation_platform import get_conf_human_workflow_arn


class ModerationStack(Stack):

    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # import existing resources
        backend_monitoring_topic = aws_sns.Topic.from_topic_arn(
            self,
            id='backend-monitoring-topic',
            topic_arn=Fn.import_value('BackendMonitoringTopicArn')
        )

        upload_bucket = aws_s3.Bucket.from_bucket_arn(
            self,
            id='upload-bucket',
            bucket_arn=Fn.import_value('UploadBucketArn')
        )

        human_workflow_arn = get_conf_human_workflow_arn(context=self)

        upload_dlq = aws_sqs.Queue(
            self,
            id='upload-dlq',
            queue_name='content-moderation-upload-dlq',
            retention_period=Duration.days(7),
        )

        upload_dlq_alarm = aws_cloudwatch.Alarm(
            self,
            id='upload-dlq-alarm',
            alarm_name='upload-dlq-alarm',
            metric=upload_dlq.metric_approximate_number_of_messages_visible(),
            threshold=1,
            evaluation_periods=1,
            comparison_operator=aws_cloudwatch.ComparisonOperator
            .GREATER_THAN_OR_EQUAL_TO_THRESHOLD,
            treat_missing_data=aws_cloudwatch.TreatMissingData.NOT_BREACHING,
            alarm_description=(
                'Alarm when there is at least 1 message in the upload DLQ'
            )
        )
        upload_dlq_alarm.add_alarm_action(
            aws_cloudwatch_actions.SnsAction(backend_monitoring_topic)
        )

        upload_sqs = aws_sqs.Queue(
            self,
            id='upload-sqs',
            queue_name='content-moderation-upload-queue',
            visibility_timeout=Duration.seconds(30),
            dead_letter_queue=aws_sqs.DeadLetterQueue(
                max_receive_count=1, queue=upload_dlq
            )
        )

        upload_bucket.add_event_notification(
            event=aws_s3.EventType.OBJECT_CREATED,
            dest=aws_s3_notifications.SqsDestination(queue=upload_sqs)
        )

        # Create text and image moderation workflows first
        text_moderation_workflow = self.create_text_moderation_workflow(
            human_workflow_arn=human_workflow_arn
        )

        image_moderation_workflow = self.create_image_moderation_workflow(
            upload_bucket=upload_bucket
        )

        self.create_start_moderation_lambda_function(
            source_queue=upload_sqs,
            monitoring_topic=backend_monitoring_topic,
            upload_bucket=upload_bucket,
            text_workflow=text_moderation_workflow,
            image_workflow=image_moderation_workflow
        )

    def create_image_moderation_workflow(
        self, upload_bucket: aws_s3.IBucket
    ) -> aws_stepfunctions.StateMachine:
        """Create a Step Function workflow for image moderation
        
        This workflow uses Amazon Rekognition to detect moderation labels and text
        in image content and evaluates the results to determine appropriate actions.
        
        Args:
            upload_bucket (aws_s3.IBucket): S3 bucket containing the images to moderate

        Returns:
            aws_stepfunctions.StateMachine: Step Functions state machine for image moderation
        """
        # Define the task to detect moderation labels using Amazon Rekognition
        detect_moderation_labels_task = aws_stepfunctions_tasks.CallAwsService(
            self,
            id='DetectModerationLabels',
            service='rekognition',
            action='detectModerationLabels',
            parameters={
                'Image':
                    {
                        'S3Object':
                            {
                                'Bucket':
                                    upload_bucket.bucket_name,
                                'Name':
                                    aws_stepfunctions.JsonPath
                                    .string_at('$.objectKey')
                            }
                    },
                'MinConfidence': 50
            },
            result_path='$.moderationLabelsResult',
            iam_resources=['*']
        )

        # Define the task to detect text in images using Amazon Rekognition
        detect_text_task = aws_stepfunctions_tasks.CallAwsService(
            self,
            id='DetectText',
            service='rekognition',
            action='detectText',
            parameters={
                'Image':
                    {
                        'S3Object':
                            {
                                'Bucket':
                                    upload_bucket.bucket_name,
                                'Name':
                                    aws_stepfunctions.JsonPath
                                    .string_at('$.objectKey')
                            }
                    }
            },
            result_path='$.textDetectionResult',
            iam_resources=['*']
        )

        # Define a task to evaluate the moderation results
        evaluate_moderation = aws_stepfunctions.Choice(
            self, id='EvaluateModeration'
        )

        # Define success path for approved content
        success_state = aws_stepfunctions.Succeed(
            self, id='ImageApproved', comment='Image passed moderation checks'
        )

        # Define a task to handle inappropriate content
        handle_inappropriate_content = aws_stepfunctions.Pass(
            self,
            id='HandleInappropriateContent',
            result_path='$.moderationDecision',
            parameters={
                'decision': 'REJECTED',
                'reason': 'Image contains inappropriate content',
                'timestamp.$': '$$.Execution.StartTime'
            }
        )

        workflow_end = aws_stepfunctions.Succeed(
            self,
            id='ImageModerationComplete',
            comment='Image moderation workflow completed'
        )

        # Create a parallel state to run both Rekognition tasks simultaneously
        parallel_tasks = aws_stepfunctions.Parallel(
            self,
            id='ParallelRekognitionTasks',
            result_path='$.parallelResults'
        )

        # Add branches to the parallel state
        parallel_tasks.branch(detect_moderation_labels_task)
        parallel_tasks.branch(detect_text_task)

        # Connect the workflow steps
        workflow_definition = parallel_tasks.next(
            evaluate_moderation.when(
                aws_stepfunctions.Condition.or_(
                    aws_stepfunctions.Condition.is_present(
                        '$.parallelResults[0].moderationLabelsResult.ModerationLabels[0]'
                    ),
                    aws_stepfunctions.Condition.is_present(
                        '$.parallelResults[0].textDetectionResult.TextDetections[0]'
                    )
                ), handle_inappropriate_content.next(workflow_end)
            ).otherwise(success_state)
        )

        # Create the state machine with error handling
        state_machine = aws_stepfunctions.StateMachine(
            self,
            id='image-moderation-workflow',
            state_machine_name='ModerationPlatform-imageModerationWorkflow',
            definition=workflow_definition,
            timeout=Duration.minutes(5),
            logs=aws_stepfunctions.LogOptions(
                destination=aws_logs.LogGroup(
                    self,
                    id='ImageModerationLogGroup',
                    log_group_name=
                    '/aws/states/ModerationPlatform-imageModerationWorkflow',
                    retention=aws_logs.RetentionDays.ONE_WEEK,
                    removal_policy=RemovalPolicy.DESTROY
                ),
                level=aws_stepfunctions.LogLevel.ALL
            )
        )

        # Grant the state machine permissions to access S3 and Rekognition
        state_machine.add_to_role_policy(
            aws_iam.PolicyStatement(
                actions=[
                    "rekognition:DetectModerationLabels",
                    "rekognition:DetectText"
                ],
                resources=["*"]
            )
        )

        state_machine.add_to_role_policy(
            aws_iam.PolicyStatement(
                actions=["s3:GetObject"],
                resources=[f"{upload_bucket.bucket_arn}/*"]
            )
        )

        Tags.of(state_machine
               ).add('Name', 'ModerationPlatform-imageModerationWorkflow')

        return state_machine

    def create_text_moderation_workflow(
        self, human_workflow_arn: str
    ) -> aws_stepfunctions.StateMachine:
        """Create a Step Function workflow for text moderation
        
        This workflow uses Amazon Comprehend to detect toxicity in text content
        and evaluates the results to determine appropriate actions.

        Args:
            human_workflow_arn (str): Workflow ARN used for human in the loop process

        Returns:
            aws_stepfunctions.StateMachine: Step Functions state machine for text moderation
        """
        # Define the task to detect toxicity using Amazon Comprehend
        detect_toxicity_task = aws_stepfunctions_tasks.CallAwsService(
            self,
            id='DetectToxicity',
            service='comprehend',
            action='detectToxicContent',
            parameters={
                'TextSegments':
                    [
                        {
                            'Text':
                                aws_stepfunctions.JsonPath
                                .string_at('$.inputText')
                        }
                    ],
                'LanguageCode':
                    aws_stepfunctions.JsonPath.string_at('$.languageCode')
            },
            result_path='$.toxicityResult',
            iam_resources=['*']
        )

        # Define a task to evaluate the toxicity results
        evaluate_toxicity = aws_stepfunctions.Choice(
            self, id='EvaluateToxicity'
        )

        # Define success path for non-toxic content
        success_state = aws_stepfunctions.Succeed(
            self, id='ContentApproved', comment='Content passed toxicity check'
        )

        # Define a task to handle highly toxic content (>0.9)
        handle_highly_toxic_content = aws_stepfunctions.Pass(
            self,
            id='HandleHighlyToxicContent',
            result_path='$.moderationDecision',
            parameters={
                'decision': 'REJECTED',
                'reason': 'Content contains highly toxic language',
                'timestamp.$': '$$.Execution.StartTime'
            }
        )

        # Define human review task for borderline cases (0.7-0.9) using Amazon A2I
        # human_review_task = aws_stepfunctions_tasks.CallAwsService(
        #     self,
        #     id='StartHumanReview',
        #     service='sagemaker',
        #     action='startHumanLoop',
        #     parameters={
        #         'FlowDefinitionArn':
        #             human_workflow_arn,
        #         'HumanLoopName.$':
        #             "States.Format('toxicity-review-{}', $.contentId)",
        #         'HumanLoopInput':
        #             {
        #                 'InputContent':
        #                     aws_stepfunctions.TaskInput.from_object(
        #                         {
        #                             'contentId.$':
        #                                 '$.contentId',
        #                             'inputText.$':
        #                                 '$.inputText',
        #                             'toxicityScore.$':
        #                                 '$.toxicityResult.ResultList[0].Toxicity',
        #                             'timestamp.$':
        #                                 '$$.Execution.StartTime'
        #                         }
        #                     ).value
        #             }
        #     },
        #     result_path='$.humanReviewRequest',
        #     iam_resources=['*']
        # )

        # Define the workflow end states
        # human_review_end = aws_stepfunctions.Succeed(
        #     self,
        #     id='A2IHumanReviewInitiated',
        #     comment='Content sent for human review via Amazon A2I'
        # )

        workflow_end = aws_stepfunctions.Succeed(
            self,
            id='ModerationComplete',
            comment='Moderation workflow completed'
        )

        # Connect the workflow steps with human-in-the-loop for scores between 0.7 and 0.9
        workflow_definition = detect_toxicity_task.next(
            evaluate_toxicity
            # .when(
            #     aws_stepfunctions.Condition.and_(
            #         aws_stepfunctions.Condition.number_greater_than_equals(
            #             '$.toxicityResult.ResultList[0].Toxicity', 0.7
            #         ),
            #         aws_stepfunctions.Condition.number_less_than(
            #             '$.toxicityResult.ResultList[0].Toxicity', 0.9
            #         )
            #     ), human_review_task.next(human_review_end)
            # )
            .when(
                aws_stepfunctions.Condition.number_greater_than_equals(
                    '$.toxicityResult.ResultList[0].Toxicity', 0.9
                ), handle_highly_toxic_content.next(workflow_end)
            ).otherwise(success_state)
        )

        # Create the state machine with error handling
        state_machine = aws_stepfunctions.StateMachine(
            self,
            id='text-moderation-workflow',
            state_machine_name='ModerationPlatform-textModerationWorkflow',
            definition=workflow_definition,
            timeout=Duration.minutes(5),
            logs=aws_stepfunctions.LogOptions(
                destination=aws_logs.LogGroup(
                    self,
                    id='TextModerationLogGroup',
                    log_group_name=
                    '/aws/states/ModerationPlatform-textModerationWorkflow',
                    retention=aws_logs.RetentionDays.ONE_WEEK,
                    removal_policy=RemovalPolicy.DESTROY
                ),
                level=aws_stepfunctions.LogLevel.ALL
            )
        )

        Tags.of(state_machine
               ).add('Name', 'ModerationPlatform-textModerationWorkflow')

        return state_machine

    def create_start_moderation_lambda_function(
        self,
        source_queue: aws_sqs.Queue,
        monitoring_topic: aws_sns.ITopic,
        upload_bucket: aws_s3.Bucket,
        text_workflow: aws_stepfunctions.StateMachine,
        image_workflow: aws_stepfunctions.StateMachine,
    ) -> aws_lambda.Function:
        """Create lambda function that starts the moderation flows
        based on the uploaded file type

        Args:
            source_queue (aws_sqs.Queue): SQS queue that contains S3 object created events
            monitoring_topic (aws_sns.ITopic): SNS topic used to send alarm notifications
            upload_bucket (aws_s3.Bucket): Upload bucket
            text_workflow (aws_stepfunctions.StateMachine): Text moderation workflow
            image_workflow (aws_stepfunctions.StateMachine): Image moderation workflow

        Returns:
            aws_lambda.Function: Lambda function
        """

        start_moderation_lambda = aws_lambda.Function(
            self,
            id='start-moderation-lambda',
            function_name='ModerationPlatform-startModeration',
            description=(
                'Lambda function used to start the moderation process for a '
                'file uploaded in the S3 upload bucket'
            ),
            runtime=aws_lambda.Runtime.PYTHON_3_12,
            code=aws_lambda.Code
            .from_asset('moderation_platform/lambdas/start_moderation_process'),
            handler='lambda_function.lambda_handler',
            memory_size=128,
            timeout=Duration.seconds(5),
            environment={
                'TEXT_WORKFLOW_ARN': text_workflow.state_machine_arn,
                'IMAGE_WORKFLOW_ARN': image_workflow.state_machine_arn,
            },
        )
        Tags.of(scope=start_moderation_lambda
               ).add('Name', 'ModerationPlatform-startModeration')

        source_queue.grant_consume_messages(start_moderation_lambda)

        aws_logs.LogGroup(
            self,
            id='start-moderation-lambda-log-group',
            log_group_name=
            f'/aws/lambda/{start_moderation_lambda.function_name}',
            retention=aws_logs.RetentionDays.ONE_WEEK,
            removal_policy=RemovalPolicy.DESTROY,
        )

        lambda_alarm = aws_cloudwatch.Alarm(
            self,
            id='start-moderation-lambda-alarm',
            alarm_name=start_moderation_lambda.function_name,
            metric=aws_cloudwatch.Metric(
                metric_name='Errors',
                namespace='AWS/Lambda',
                dimensions_map={
                    'FunctionName': start_moderation_lambda.function_name,
                    'Resource': start_moderation_lambda.function_name
                },
                statistic='sum',
            ).with_(period=Duration.seconds(3600), statistic='sum'),
            threshold=1,
            evaluation_periods=1,
            alarm_description=(
                'CloudWatch alarm for Lambda function '
                f'{start_moderation_lambda.function_name}'
            ),
            comparison_operator=aws_cloudwatch.ComparisonOperator
            .GREATER_THAN_OR_EQUAL_TO_THRESHOLD,
            treat_missing_data=aws_cloudwatch.TreatMissingData.MISSING,
        )
        lambda_alarm.add_alarm_action(
            aws_cloudwatch_actions.SnsAction(monitoring_topic)
        )

        start_moderation_lambda.add_event_source(
            aws_lambda_event_sources.SqsEventSource(
                queue=source_queue,
                batch_size=1,
                enabled=True,
            )
        )

        # Grant permissions to start Step Functions executions
        start_moderation_lambda.add_to_role_policy(
            aws_iam.PolicyStatement(
                actions=["states:StartExecution"],
                resources=[
                    text_workflow.state_machine_arn,
                    image_workflow.state_machine_arn
                ]
            )
        )

        # Grant permission to read files from the upload bucket
        start_moderation_lambda.add_to_role_policy(
            aws_iam.PolicyStatement(
                actions=['s3:GetObject'],
                resources=[f'{upload_bucket.bucket_arn}/*']
            )
        )

        return start_moderation_lambda
