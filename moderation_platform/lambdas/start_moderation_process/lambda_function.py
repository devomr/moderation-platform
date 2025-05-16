"""Lambda function that starts the moderation workflow based on the uploaded file type
"""
# Standard imports
import json
import os
import logging
from typing import Literal, Union
from urllib.parse import unquote_plus

# Third party imports
import boto3

# Configure logging
logger = logging.getLogger()
logger.setLevel(logging.INFO)

# Initialize AWS clients
sfn_client = boto3.client('stepfunctions')
s3_client = boto3.client('s3')

# Constants for file type determination
TEXT_EXTENSIONS = ['.txt', '.md']
IMAGE_EXTENSIONS = ['.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp']

# Get the ARNs of the Step Functions state machines from environment variables
# These will be set in the CDK stack
TEXT_WORKFLOW_ARN = os.environ.get('TEXT_WORKFLOW_ARN')
IMAGE_WORKFLOW_ARN = os.environ.get('IMAGE_WORKFLOW_ARN')


def lambda_handler(event: dict, context: dict):
    """Lambda handler that processes S3 events from SQS and starts the appropriate moderation workflow.
    
    Args:
        event (dict): The event dict containing SQS messages with S3 events
        context (object): Lambda context
        
    Returns:
        dict: Response indicating processing status
    """
    del context # unused

    logger.info(f'Received event: {json.dumps(event)}')

    if not TEXT_WORKFLOW_ARN or not IMAGE_WORKFLOW_ARN:
        raise ValueError(
            'TEXT_WORKFLOW_ARN or IMAGE_WORKFLOW_ARN environment variable not set'
        )

    for record in event.get('Records', []):
        sqs_body = json.loads(record.get('body', '{}'))

        for s3_record in sqs_body.get('Records', []):
            if not is_allowed_event(s3_record):
                logger.warning(
                    f'Skipping non-S3 object creation event: {s3_record}'
                )
                continue
            
            # Extract S3 bucket and object key
            process_queue_record(s3_record)


def process_queue_record(record: dict) -> None:
    """Process an SQS queue record that has the S3 upload event

    Args:
        record (dict): S3 upload event record

    Raises:
        ValueError: In case the S3 object key is not present 
        or the file type it's not supported
    """
    s3_object = record.get('s3', {})
    bucket_name = s3_object.get('bucket', {}).get('name')
    object_key = s3_object.get('object',{}).get('key')

    if not object_key:
        raise ValueError(
            f'Missing object key in record: {record}'
        )

    # URL decode the object key
    object_key = unquote_plus(object_key)

    # Determine file type
    file_type = determine_file_type(object_key)
    logger.info(
        f'Determined file type for {object_key}: {file_type}'
    )
    
    # Start the appropriate workflow based on file type
    if file_type == 'text':
        object = s3_client.get_object(
            Bucket=bucket_name,
            Key=object_key
        )
        content = object['Body'].read().decode('utf-8')

        return start_text_moderation_workflow(
            text=content,
            language_code='en'
        )
        
    if file_type == 'image':
        return start_image_moderation_workflow(object_key=object_key)
        
    raise ValueError(f'Unsupported file type for {object_key}')


def start_text_moderation_workflow(text: str, language_code: str = 'en') -> None:
    """Start text moderation workflow

    Args:
        text (str): Input text
        language_code (str, optional): Language code. Defaults to 'en'.
    """
    response = sfn_client.start_execution(
        stateMachineArn=TEXT_WORKFLOW_ARN,
        input=json.dumps(
            {
                'inputText': text,
                'languageCode': language_code,
            }
        )
    )
    logger.info(
        f'Started text moderation workflow: {response['executionArn']}'
    )


def start_image_moderation_workflow(object_key: str) -> None:
    """Start image moderation workflow

    Args:
        object_key (str): S3 object key
    """
    response = sfn_client.start_execution(
        stateMachineArn=IMAGE_WORKFLOW_ARN,
        input=json.dumps({
            'objectKey': object_key,
        })
    )
    logger.info(
        f'Started image moderation workflow: {response['executionArn']}'
    )


def is_allowed_event(s3_record: dict) -> bool:
    """Check if the event is an allowed S3 object creation event
    
    Args:
        s3_record (dict): The S3 event record
        
    Returns:
        bool: True if event is allowed, False otherwise
    """
    return (s3_record.get('eventSource') == 'aws:s3' and 
            s3_record.get('eventName', '').startswith('ObjectCreated:'))


def determine_file_type(object_key: str) -> Literal['text', 'image', 'unknown']:
    """Determine if the file is text or image based on its extension
    
    Args:
        object_key (str): The S3 object key
        
    Returns:
        str: 'text', 'image', or 'unknown'
    """
    # Get the file extension (lowercase)
    _, ext = os.path.splitext(object_key.lower())

    if ext in TEXT_EXTENSIONS:
        return 'text'

    if ext in IMAGE_EXTENSIONS:
        return 'image'

    return 'unknown'
