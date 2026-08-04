FROM public.ecr.aws/lambda/python:3.11

COPY services/github_tool/requirements.txt ${LAMBDA_TASK_ROOT}/requirements.txt
RUN pip install --no-cache-dir --target "${LAMBDA_TASK_ROOT}" -r "${LAMBDA_TASK_ROOT}/requirements.txt" \
    && rm -f "${LAMBDA_TASK_ROOT}/requirements.txt"

COPY services/ ${LAMBDA_TASK_ROOT}/services/
COPY contracts/ ${LAMBDA_TASK_ROOT}/contracts/
COPY schemas/ ${LAMBDA_TASK_ROOT}/schemas/

CMD ["services.github_tool.handler.lambda_handler"]
