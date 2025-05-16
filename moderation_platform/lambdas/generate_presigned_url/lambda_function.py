"""Lambda function that generates a presigned URL for uploading files to S3
"""
# Standard imports
import json
import os
import logging
import uuid
from typing import Any

# Third party imports
import boto3
from botocore.exceptions import ClientError

# Configure logging
logger = logging.getLogger()
logger.setLevel(logging.INFO)

# Initialize S3 client
s3_client = boto3.client('s3')

# Get the upload bucket name from environment variables
UPLOAD_BUCKET = os.environ.get('UPLOAD_BUCKET')


def lambda_handler(event: dict, context: dict) -> dict[str, Any]:
    """Generate a presigned URL for uploading a file to S3
    
    Args:
        event (dict): API Gateway event
        context (dict): Lambda context
        
    Returns:
        dict[str, Any]: Response containing the presigned URL
    """
    del context  # unused

    logger.info(f'Received event: {json.dumps(event)}')

    if not UPLOAD_BUCKET:
        raise ValueError('UPLOAD_BUCKET environment variable not set')

    body = json.loads(event.get('body', '{}'))
    file_name = body.get('fileName')
    content_type = body.get('contentType')

    if not file_name or not content_type:
        return build_http_response(
            400,
            json.dumps(
                {
                    'error':
                        'Missing required parameters: fileName and contentType'
                }
            )
        )

    # Generate a unique object key to prevent overwriting existing files
    object_key = f'{uuid.uuid4()}-{file_name}'

    # Generate the presigned URL
    presigned_url = generate_presigned_url(
        bucket_name=UPLOAD_BUCKET,
        object_key=object_key,
        content_type=content_type,
        expiration=3600  # URL expires in 1 hour
    )

    return build_http_response(
        200,
        json.dumps({
            'presignedUrl': presigned_url,
            'objectKey': object_key
        })
    )


def build_http_response(code: int, body: str) -> dict:
    """Build the HTTP response object

    Args:
        code (int): HTTP code
        body (str): HTTP response body

    Returns:
        dict: HTTP response
    """
    return {
        'statusCode': code,
        'headers':
            {
                'Content-Type': 'application/json',
                'Access-Control-Allow-Origin': '*'
            },
        'body': body
    }


def generate_presigned_url(
    bucket_name: str,
    object_key: str,
    content_type: str,
    expiration: int = 3600
) -> str:
    """Generate a presigned URL for uploading a file to S3
    
    Args:
        bucket_name (str): S3 bucket name
        object_key (str): S3 object key
        content_type (str): Content type of the file
        expiration (int, optional): URL expiration time in seconds. Defaults to 3600 (1 hour).
        
    Returns:
        str: Presigned URL
        
    Raises:
        ClientError: If there's an error generating the presigned URL
    """
    try:
        response = s3_client.generate_presigned_url(
            'put_object',
            Params={
                'Bucket': bucket_name,
                'Key': object_key,
                'ContentType': content_type
            },
            ExpiresIn=expiration,
            HttpMethod='PUT'
        )

        logger.info(f'Generated presigned URL for {object_key}')
        return response

    except ClientError as e:
        logger.error(f'Error generating presigned URL: {e}')
        raise
