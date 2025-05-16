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

        self.create_start_moderation_lambda_function(
            source_queue=upload_sqs,
            monitoring_topic=backend_monitoring_topic,
        )

        self.create_text_moderation_workflow(
            human_workflow_arn=human_workflow_arn
        )

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
    ) -> aws_lambda.Function:
        """Create lambda function that starts the moderation flows
        based on the uploaded file type

        Args:
            source_queue (aws_sqs.Queue): SQS queue that contains S3 object created events
            monitoring_topic (aws_sns.ITopic): SNS topic used to send alarm notifications

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

        return start_moderation_lambda
