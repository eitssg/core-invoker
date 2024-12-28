import core_logging as log

import core_framework as util
from core_framework.constants import V_LOCAL, TR_RESPONSE, OBJ_ARTEFACTS, V_SERVICE

import core_helper.aws as aws

from core_component_compiler.handler import handler as component_compiler_handler
from core_deployspec_compiler.handler import handler as deployspec_compiler_handler
from core_runner.handler import handler as runner_handler

from core_framework.models import TaskPayload
from core_framework.magic import MagicBucket


def execute_pipeline_compiler(task_payload: TaskPayload) -> dict:
    """
    Execute the pipeline compiler lambda function

    Args:
        package_details (dict): the package details object
        deployment_details (dict): the deployment details object

    Returns:
        dict: the results of the component compiler
    """

    if util.is_local_mode():
        return component_compiler_handler(task_payload.model_dump(), None)

    arn = util.get_component_compiler_lambda_arn()
    result = aws.invoke_lambda(arn, task_payload.model_dump())
    if TR_RESPONSE not in result:
        raise RuntimeError(
            "Pipeline compiler response does not contain a response: {}".format(result)
        )
    return result[TR_RESPONSE]


def execute_deployspec_compiler(task_payload: TaskPayload) -> dict:
    """
    Execute the deployspec compiler Lambda function

    Args:
        task_payload (TaskPayload): the task definition

    Returns:
        dict: the results of the deployspec compile
    """

    if util.is_local_mode():
        return deployspec_compiler_handler(task_payload.model_dump(), None)

    arn = util.get_deployspec_compiler_lambda_arn()
    result = aws.invoke_lambda(arn, task_payload.model_dump())
    if TR_RESPONSE not in result:
        raise RuntimeError(
            "Deployspec compiler response does not contain a response: {}".format(
                result
            )
        )
    return result[TR_RESPONSE]


def execute_runner(task_payload: TaskPayload) -> dict:
    """
    Execute the runner step functions

    It is assumed that task_payload is fully populated with the
    location of the files for Package, Action, and State artefacts.

    Args:
        task_payload (TaskPayload): the task definition.

    Returns:
        dict: results of the runner start request
    """

    if util.is_local_mode():
        return runner_handler(task_payload.model_dump(), None)

    arn = util.get_start_runner_lambda_arn()
    response = aws.invoke_lambda(arn, task_payload.model_dump())
    if TR_RESPONSE not in response:
        raise RuntimeError(
            "Runner response does not contain a response: {}".format(response)
        )
    return response[TR_RESPONSE]


def copy_to_artefacts(task_payload: TaskPayload) -> dict:
    """
    Copies the packages to the artefacts bucket

    Args:
        task_payload (TaskPayload): The task payload

    Raises:
        RuntimeError: Something unexpected happened
        ValueError: Package key not found in task payload

    Returns:
        dict: results of the copy
    """

    artefact_bucket_region = util.get_artefact_bucket_region()
    artefact_bucket_name = util.get_artefact_bucket_name()

    package = task_payload.Package
    if package.BucketRegion != artefact_bucket_region:
        raise RuntimeError(
            artefact_bucket_region,
            "Source S3 bucket must be in region '{}'".format(artefact_bucket_region),
        )
    if not package.Key:
        raise ValueError("Package key not found in task payload")

    object_name = package.Key.rsplit("/", 1)[-1]

    dd = task_payload.DeploymentDetails
    destination_key = dd.get_object_key(
        OBJ_ARTEFACTS, object_name, s3=package.Mode == V_SERVICE
    )

    destination = {
        "Bucket": artefact_bucket_name,
        "Key": destination_key,
        "VersionId": None,
    }

    log.info(
        "Copying object to artefacts",
        details={"Source": package, "Destination": destination},
    )

    if package.Mode == V_LOCAL:
        artefact_bucket = MagicBucket(artefact_bucket_name, artefact_bucket_region)
    else:
        s3 = aws.s3_resource(artefact_bucket_region)
        artefact_bucket = s3.Bucket(artefact_bucket_name)

    destination_object = artefact_bucket.Object(destination_key)

    # Copy the object
    copy_source = {"Bucket": package.BucketName, "Key": package.Key, "VersionId": None}

    response = destination_object.copy_from(
        ACL="bucket-owner-full-control",
        CopySource=copy_source,
        ServerSideEncryption="AES256",
    )

    # Return details of the new object
    return response
