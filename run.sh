#!/bin/sh -ex
# Runner script that loads docker secrets as environment variables

# Update all environment variables with the secrets
: ${DOCKER_SECRETS_DIR:=/run/secrets}
if [ -e "$DOCKER_SECRETS_DIR" ] ; then
  for secret_file in "$DOCKER_SECRETS_DIR"/* ; do
    secret=$(basename "$secret_file")
    eval "tmp=\$$secret"
    test -z "$tmp"
    export "$secret"="$(cat "$secret_file")"
  done
fi

# Run the server
: ${GD_HOST:=0.0.0.0}
: ${GD_PORT:=8000}
python -umsanic server.app --host="$GD_HOST" --port="$GD_PORT"
