# Third party imports
from constructs import Construct
from aws_cdk import CfnOutput, Stack, Tags, RemovalPolicy, aws_cognito


class CognitoStack(Stack):

    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        user_pool = aws_cognito.UserPool(
            self,
            id='user-pool',
            user_pool_name='moderation-platform-user-pool',
            sign_in_aliases={'email': True},
            password_policy={
                'min_length': 8,
                'require_lowercase': True,
                'require_uppercase': True,
                'require_digits': True,
                'require_symbols': True
            },
            user_verification={
                'email_subject':
                    'You need to verify your email',
                'email_body':
                    'Thanks for signing up Your verification code is {####}',
                'email_style':
                    aws_cognito.VerificationEmailStyle.CODE,
            },
            auto_verify={'email': True},
            # TODO: distroy the bucket in `dev` env
            removal_policy=RemovalPolicy.RETAIN
        )

        Tags.of(scope=user_pool).add('Name', 'moderation-platform-user-pool')

        user_pool.add_client(
            id='app-client',
            user_pool_client_name='moderation-platform-app-client',
            auth_flows={
                'user_password': True,
            }
        )

        # define stack exports
        CfnOutput(
            self,
            id='user-pool-output',
            value=user_pool.user_pool_arn,
            export_name='ModerationPlatformUserPoolArn',
        )
