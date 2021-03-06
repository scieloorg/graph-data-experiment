#!/bin/sh -e
# Runner script that loads docker secrets as environment variables

# Update all environment variables with the secrets
: ${DOCKER_SECRETS_DIR:=/run/secrets}
if [ -e "$DOCKER_SECRETS_DIR" ] ; then
  for secret_file in "$DOCKER_SECRETS_DIR"/* ; do
    secret=$(basename "$secret_file")
    eval "tmp=\$$secret"
    if [ -n "$tmp" ] ; then
      echo "Multiple $secret definition," \
           "it's both a secret and an environment variable"
      false # Propagate the error
    fi
    export "$secret"="$(cat "$secret_file")"
  done
fi

# Run the server
: ${GD_HOST:=0.0.0.0}
: ${GD_PORT:=8000}
python -umsanic gd.app --host="$GD_HOST" --port="$GD_PORT"
