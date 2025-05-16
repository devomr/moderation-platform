#!/usr/bin/env python3

# Third party imports
from constructs import Construct


def get_conf_account_id(context: Construct) -> str:
    """Get configured AWS account id

    Args:
        context (Construct): Context object

    Raises:
        KeyError: Exception in case `AccountId` is not configured

    Returns:
        str: AWS account id
    """
    try:
        return context.node.try_get_context('ModerationPlatform')['AccountId']
    except KeyError:
        raise KeyError('ModerationPlatform.AccountId not found in cdk.json')


def get_conf_region(context: Construct) -> str:
    """Get configured AWS region

    Args:
        context (Construct): Context object

    Raises:
        KeyError: Exception in case `Region` is not configured

    Returns:
        str: AWS region
    """
    try:
        return context.node.try_get_context('ModerationPlatform')['Region']
    except KeyError:
        raise KeyError('ModerationPlatform.Region not found in cdk.json')


def get_conf_human_workflow_arn(context: Construct) -> str:
    """Get configured human in the loop workflow ARN

    Args:
        context (Construct): Context object

    Raises:
        KeyError: Exception in case `HumanWorkflowArn` is not configured

    Returns:
        str: Workflow ARN
    """
    try:
        return context.node.try_get_context('ModerationPlatform'
                                           )['HumanWorkflowArn']
    except KeyError:
        raise KeyError(
            'ModerationPlatform.HumanWorkflowArn not found in cdk.json'
        )
