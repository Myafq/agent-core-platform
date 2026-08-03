FROM public.ecr.aws/amazonlinux/amazonlinux:2023

ARG GH_VERSION=2.68.1

RUN dnf install -y \
      bash \
      ca-certificates \
      findutils \
      git \
      gzip \
      jq \
      make \
      procps-ng \
      python3 \
      python3-pip \
      tar \
      unzip \
      which \
    && curl --fail --location --silent --show-error \
      "https://github.com/cli/cli/releases/download/v${GH_VERSION}/gh_${GH_VERSION}_linux_arm64.tar.gz" \
      --output /tmp/gh.tar.gz \
    && tar -xzf /tmp/gh.tar.gz -C /tmp \
    && install -m 0755 "/tmp/gh_${GH_VERSION}_linux_arm64/bin/gh" /usr/local/bin/gh \
    && python3 -m pip install --no-cache-dir boto3 \
    && rm -rf /tmp/gh* /var/cache/dnf

COPY github-app-token /usr/local/bin/github-app-token
COPY github-app-git-credential /usr/local/bin/github-app-git-credential
RUN chmod 0755 /usr/local/bin/github-app-token /usr/local/bin/github-app-git-credential

WORKDIR /mnt/workspace
