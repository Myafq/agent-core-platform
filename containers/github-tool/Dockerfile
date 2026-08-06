FROM public.ecr.aws/lambda/python:3.11

COPY containers/github-tool/service/github_tool/requirements.txt ${LAMBDA_TASK_ROOT}/requirements.txt
RUN pip install --no-cache-dir --target "${LAMBDA_TASK_ROOT}" -r "${LAMBDA_TASK_ROOT}/requirements.txt" \
    && rm -f "${LAMBDA_TASK_ROOT}/requirements.txt"

COPY containers/github-tool/service/github_tool/ ${LAMBDA_TASK_ROOT}/github_tool/
COPY contracts/contract_validation.py ${LAMBDA_TASK_ROOT}/contracts/contract_validation.py
COPY schemas/github-tool-invocation-v1alpha1.schema.json ${LAMBDA_TASK_ROOT}/schemas/
COPY schemas/github-tool-response-v1alpha1.schema.json ${LAMBDA_TASK_ROOT}/schemas/

CMD ["github_tool.handler.lambda_handler"]
