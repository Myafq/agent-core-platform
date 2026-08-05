FROM public.ecr.aws/lambda/python:3.11

# Only the service's own code plus the shared state-signing module it imports.
# No third-party dependencies: the callback is stdlib plus Lambda-provided
# boto3, and the rest of the repo's client-only packages stay out of the image.
COPY services/__init__.py ${LAMBDA_TASK_ROOT}/services/
COPY services/slack_oauth_callback/ ${LAMBDA_TASK_ROOT}/services/slack_oauth_callback/
COPY contracts/slack_oauth_state.py ${LAMBDA_TASK_ROOT}/contracts/

CMD ["services.slack_oauth_callback.handler.lambda_handler"]
