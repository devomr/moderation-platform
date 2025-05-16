# Third party imports
from constructs import Construct
from aws_cdk import (
    Stack,
    Tags,
    aws_codebuild,
    aws_codepipeline,
    aws_codepipeline_actions,
    aws_iam,
    SecretValue,
)


class CICDStack(Stack):
    """CI/CD Stack for the Moderation Platform
    
    This stack creates a CodePipeline that is triggered when code is pushed to a GitHub repository.
    The pipeline builds and deploys the CDK stacks.
    """

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        repository_name: str,
        owner: str,
        branch_name: str = 'main',
        **kwargs
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # Create a CodeBuild project for CDK deployment
        build_project = aws_codebuild.PipelineProject(
            self,
            id='build-project',
            project_name=f'{repository_name}-build',
            description='Build and deploy the Moderation Platform CDK stacks',
            environment=aws_codebuild.BuildEnvironment(
                build_image=aws_codebuild.LinuxBuildImage.STANDARD_7_0,
                privileged=True,
            ),
            build_spec=aws_codebuild.BuildSpec.from_object(
                {
                    'version': '0.2',
                    'phases':
                        {
                            'install':
                                {
                                    'runtime-versions': {
                                        'python': '3.12'
                                    },
                                    'commands':
                                        [
                                            'npm install -g aws-cdk',
                                            'pip install -r requirements.txt',
                                            'pip install -r requirements-dev.txt',
                                        ]
                                },
                            'build':
                                {
                                    'commands':
                                        [
                                            'cdk deploy --all --require-approval never'
                                        ]
                                }
                        },
                    'artifacts':
                        {
                            'base-directory': 'cdk.out',
                            'files': ['**/*']
                        }
                }
            ),
            environment_variables={
                'CDK_DEFAULT_ACCOUNT': {
                    'value': self.account
                },
                'CDK_DEFAULT_REGION': {
                    'value': self.region
                }
            }
        )
        Tags.of(build_project).add('Name', f'{repository_name}-build')

        # Grant the build project permissions to deploy CDK stacks
        build_project.add_to_role_policy(
            aws_iam.PolicyStatement(
                actions=[
                    'cloudformation:*',
                    's3:*',
                    'iam:*',
                    'lambda:*',
                    'apigateway:*',
                    'ec2:*',
                    'ssm:*',
                    'states:*',
                    'logs:*',
                    'sns:*',
                    'sqs:*',
                    'rekognition:*',
                    'comprehend:*',
                    'sagemaker:*',
                ],
                resources=['*']
            )
        )

        # Create the pipeline
        pipeline = aws_codepipeline.Pipeline(
            self,
            id='pipeline',
            pipeline_name=f'{repository_name}-pipeline',
            restart_execution_on_update=True,
        )
        Tags.of(pipeline).add('Name', f'{repository_name}-pipeline')

        # Add source stage with GitHub as source
        source_output = aws_codepipeline.Artifact()
        source_action = aws_codepipeline_actions.GitHubSourceAction(
            action_name='GitHub_Source',
            owner=owner,
            repo=repository_name,
            branch=branch_name,
            oauth_token=SecretValue.secrets_manager('github-token'),
            output=source_output,
        )
        pipeline.add_stage(stage_name='Source', actions=[source_action])

        # Add build and deploy stage
        build_action = aws_codepipeline_actions.CodeBuildAction(
            action_name='BuildAndDeploy',
            project=build_project,
            input=source_output,
            outputs=[aws_codepipeline.Artifact()]
        )
        pipeline.add_stage(stage_name='BuildAndDeploy', actions=[build_action])
