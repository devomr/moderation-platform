#!/usr/bin/env python3

# Third party imports
from aws_cdk import App, Environment

# Local imports
from moderation_platform import get_conf_account_id, get_conf_region
from moderation_platform.observability_stack import ObservabilityStack
from moderation_platform.s3_stack import S3Stack
from moderation_platform.moderation_stack import ModerationStack

app = App()
env_dev = Environment(
    account=get_conf_account_id(context=app),
    region=get_conf_region(context=app)
)

# Create stacks here
print()

observability_stack = ObservabilityStack(app, 'ObservabilityStack', env=env_dev)
s3_stack = S3Stack(app, 'S3Stack', env=env_dev)

moderation_stack = ModerationStack(app, 'ModerationStack', env=env_dev)
moderation_stack.add_dependency(observability_stack)
moderation_stack.add_dependency(s3_stack)

app.synth()
