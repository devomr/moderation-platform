# Third party imports
from constructs import Construct
from aws_cdk import CfnOutput, Stack, Tags, aws_sns


class ObservabilityStack(Stack):

    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # define SNS topic for backend notifications
        backend_monitoring_topic = aws_sns.Topic(
            scope=self,
            id='backend-monitoring-topic',
            topic_name='backend-monitoring-topic',
            display_name='Backend Topic - Moderation Platform',
        )
        Tags.of(scope=backend_monitoring_topic
               ).add('Name', 'backend-monitoring-topic')

        # define stack exports
        CfnOutput(
            self,
            id='backend-monitoring-topic',
            value=backend_monitoring_topic.topic_arn,
            export_name='BackendMonitoringTopicArn',
        )
