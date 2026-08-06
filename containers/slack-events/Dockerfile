FROM public.ecr.aws/lambda/python:3.11

COPY containers/slack-events/service/slack_events/requirements.txt ${LAMBDA_TASK_ROOT}/requirements.txt
RUN pip install --no-cache-dir --target "${LAMBDA_TASK_ROOT}" -r "${LAMBDA_TASK_ROOT}/requirements.txt" \
    && rm -f "${LAMBDA_TASK_ROOT}/requirements.txt"

COPY containers/slack-events/service/ ${LAMBDA_TASK_ROOT}/
COPY clients/channel/ ${LAMBDA_TASK_ROOT}/clients/channel/
COPY contracts/contract_validation.py ${LAMBDA_TASK_ROOT}/contracts/
COPY schemas/channel-message-v1alpha1.schema.json ${LAMBDA_TASK_ROOT}/schemas/

CMD ["slack_events.ingress.lambda_handler"]
