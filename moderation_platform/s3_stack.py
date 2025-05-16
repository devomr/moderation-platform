# Third party imports
from constructs import Construct
from aws_cdk import CfnOutput, RemovalPolicy, Stack, aws_s3


class S3Stack(Stack):

    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        upload_bucket = aws_s3.Bucket(
            self,
            id='upload-bucket',
            bucket_name='content-moderation-upload-bucket',
            public_read_access=False,
            block_public_access=aws_s3.BlockPublicAccess.BLOCK_ALL,
            # TODO: distroy the bucket in `dev` env
            removal_policy=RemovalPolicy.RETAIN
        )

        # define stack exports
        CfnOutput(
            self,
            id='upload-bucket-output',
            value=upload_bucket.bucket_arn,
            export_name='UploadBucketArn'
        )
