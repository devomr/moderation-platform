#!/usr/bin/env python3

# Third party imports
from aws_cdk import App, Environment

# Local imports
from moderation_platform import (
    get_conf_account_id, get_conf_region, get_conf_repository_name,
    get_conf_repository_owner, get_conf_branch_name
)
from moderation_platform.observability_stack import ObservabilityStack
from moderation_platform.s3_stack import S3Stack
from moderation_platform.moderation_stack import ModerationStack
from moderation_platform.cicd_stack import CICDStack
from moderation_platform.cognito_stack import CognitoStack
from moderation_platform.api_gateway_stack import ApiGatewayStack

app = App()
env_dev = Environment(
    account=get_conf_account_id(context=app),
    region=get_conf_region(context=app)
)

# Create stacks here
cognito_stack = CognitoStack(app, 'CognitoStack', env=env_dev)
observability_stack = ObservabilityStack(app, 'ObservabilityStack', env=env_dev)
s3_stack = S3Stack(app, 'S3Stack', env=env_dev)

api_gateway_stack = ApiGatewayStack(app, 'ApiGatewayStack', env=env_dev)
api_gateway_stack.add_dependency(observability_stack)
api_gateway_stack.add_dependency(cognito_stack)

moderation_stack = ModerationStack(app, 'ModerationStack', env=env_dev)
moderation_stack.add_dependency(observability_stack)
moderation_stack.add_dependency(s3_stack)

# Create CI/CD stack
cicd_stack = CICDStack(
    app,
    'CICDStack',
    repository_name=get_conf_repository_name(context=app),
    owner=get_conf_repository_owner(context=app),
    branch_name=get_conf_branch_name(context=app),
    env=env_dev
)

app.synth()
