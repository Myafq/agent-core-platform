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
      tar \
      unzip \
      which \
    && curl --fail --location --silent --show-error \
      "https://github.com/cli/cli/releases/download/v${GH_VERSION}/gh_${GH_VERSION}_linux_arm64.tar.gz" \
      --output /tmp/gh.tar.gz \
    && tar -xzf /tmp/gh.tar.gz -C /tmp \
    && install -m 0755 "/tmp/gh_${GH_VERSION}_linux_arm64/bin/gh" /usr/local/bin/gh \
    && rm -rf /tmp/gh* /var/cache/dnf

WORKDIR /mnt/workspace
