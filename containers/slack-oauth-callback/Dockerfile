FROM public.ecr.aws/lambda/python:3.11

# Only the service's own code plus the shared state-signing module it imports.
# No third-party dependencies: the callback is stdlib plus Lambda-provided
# boto3, and the rest of the repo's client-only packages stay out of the image.
COPY containers/slack-oauth-callback/service/ ${LAMBDA_TASK_ROOT}/
COPY contracts/slack_oauth_state.py ${LAMBDA_TASK_ROOT}/contracts/

CMD ["slack_oauth_callback.handler.lambda_handler"]
