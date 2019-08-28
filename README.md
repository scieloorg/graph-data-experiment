# Graph data experiment

Experiment on persistent data history storage as a DAG.

The current working directory for all commands described here
is the repository root directory.

The extra tools required for running this experiment as described here
are Docker and [jq](https://github.com/stedolan/jq).


## Database setup

It's based on PostgreSQL.
For a single temporary example
(i.e., an environment with no persistent "volume"),
one can use the default Docker image, for example:

```bash
docker network create gd-network
docker run -d \
           -p 5432:5432 \
           -e POSTGRES_USER=user \
           -e POSTGRES_PASSWORD=pass \
           -e POSTGRES_DB=histdb \
           --name pgdb \
           --network gd-network \
           postgres:11.5-alpine
```

One still needs to initialize this database.
Assuming you have ``alembic`` and ``psycopg2``
(from the operating system packages
 or from a virtual environment
 such as the one described in the back-end session of this text,
 by installing the frozen versions of these packages
 with ``pip install -r requirements.migrations.txt``
 or their current version
 with ``pip install alembic psycopg2``),
you can bootstrap that database with the migration scripts:

```bash
export GD_PGSQL_DSN=postgres://user:pass@localhost:5432/histdb
alembic upgrade head
```

These "local" PostgreSQL credentials are the ones
from the docker call in the example.
To bootstrap this otherwhere
just replace the `GD_PGSQL_DSN` environment variable
with the actual credentials.


## LDAP Authentication setup

For testing the application in an isolated environment,
one can run OpenLDAP and populate it with some users.
An example using OpenLDAP v2.4.47:

```bash
LDAP_MAIN_PASSWORD=$(head -c9 /dev/urandom | hexdump -e '"%x"')
echo 'Save this after running for the first time!!!'
echo "export LDAP_MAIN_PASSWORD='$LDAP_MAIN_PASSWORD'"

docker run -d \
           -p 636:636 \
           --name gd-ldap \
           --network gd-network \
           --env LDAP_ADMIN_PASSWORD="$LDAP_MAIN_PASSWORD" \
           --env LDAP_CONFIG_PASSWORD="$LDAP_MAIN_PASSWORD" \
           --env LDAP_DOMAIN="graph.data" \
           --env LDAP_ORGANISATION="Organise & Organize Company Ltd." \
           --env LDAP_TLS_VERIFY_CLIENT=try \
           osixia/openldap:1.2.5

# Create an organizational unit, a common user and an "admin" user
docker exec -i gd-ldap ldapadd -x \
                               -D "cn=admin,dc=graph,dc=data" \
                               -w "$LDAP_MAIN_PASSWORD" \
                               -H ldap://localhost \
                               <<EOF
dn: ou=users,dc=graph,dc=data
ou: users
objectClass: organizationalUnit

dn: cn=Feykee Yusahr,ou=users,dc=graph,dc=data
sn: Yusahr
cn: Feykee Yusahr
uid: feykee
objectClass: person
objectClass: posixAccount
uidNumber: 1000
gidNumber: 500
homeDirectory: /home/users/feykee
userPassword: $(docker exec -i gd-ldap slappasswd -s "userpw")

dn: uid=admin4gd,dc=graph,dc=data
uid: admin4gd
objectClass: account
objectClass: simpleSecurityObject
userPassword: $(docker exec -i gd-ldap slappasswd -s "adminpw")
EOF

# Grant access rights to the "admin4gd" user
docker exec -i gd-ldap ldapmodify -x \
                                  -D "cn=admin,cn=config" \
                                  -w "$LDAP_MAIN_PASSWORD" \
                                  -H ldap://localhost <<EOF
dn: olcDatabase={1}mdb,cn=config
changetype: modify
add: olcAccess
olcAccess: {1}to dn.subtree="ou=users,dc=graph,dc=data"
  by dn.base="uid=admin4gd,dc=graph,dc=data" write
EOF
```

To manually configure this LDAP using a web UI, one can use this:

```bash
docker run --rm \
           -d \
           --name gd-ldap-admin \
           --network gd-network \
           --env PHPLDAPADMIN_LDAP_HOSTS=gd-ldap \
           osixia/phpldapadmin:0.8.0

# To show the web UI URL
GD_LDAPADMIN_IP=$(
  docker container inspect gd-ldap-admin \
  | jq -r '.[].NetworkSettings.Networks["gd-network"].IPAddress'
)
echo https://$GD_LDAPADMIN_IP
```


## Back-end setup (development)

This server requires Python 3.7+.
To install the server dependencies/requirements (frozen versions)
in a virtual environment:

```bash
python3 -m venv venv # Create a virtual environment
. venv/bin/activate # Activate the virtual environment
pip install -r requirements.txt
```

Or, to install the current version of the dependencies
instead of the frozen versions
(these are the direct dependencies):

```bash
pip install sanic sanic-cors sanic-prometheus \
            asyncpgsa sqlalchemy bonsai jwcrypto
```

To run the web server in a already activated virtual environment
(replace the octet and credentials with the actual ones):

```bash
export GD_PGSQL_DSN=postgres://user:pass@localhost:5432/histdb
export GD_LDAP_DSN="ldaps://uid=admin4gd,dc=graph,dc=data:adminpw@`
                           `localhost/ou=users,dc=graph,dc=data`
                           `?user_field=uid"
export GD_JWK_OCTET="$(head -c32 /dev/urandom | base64)"
./server.py
```

The Prometheus `/metrics` entry point is part of this application.
To use another port to serve for such route,
specify the port in the `GD_PROMETHEUS_PORT` environment variable.


## Front-end setup (development)

To create the `node_modules` directory with the JavaScript packages:

```bash
npm install
```

To create the `/dist` directory (required by the back-end):

```bash
npx webpack --mode production
```

To test/debug the front-end code (assuming the back-end is running):

```bash
npx webpack-dev-server --mode development --open
```


## Easier back-end and front-end setup using Docker

To run the server in a "production"-like container
using the development configuration,
one can use:

```bash
docker build -t gd .
docker run --rm \
           --network gd-network \
           -e GD_PGSQL_DSN=postgres://user:pass@pgdb:5432/histdb \
           -e GD_LDAP_DSN="ldaps://uid=admin4gd,dc=graph,dc=data` \
                          `:adminpw@gd-ldap` \
                          `/ou=users,dc=graph,dc=data?user_field=uid" \
           -e GD_JWK_OCTET="$(head -c32 /dev/urandom | base64)" \
           -e GD_PROMETHEUS_PORT=7000 \
           -p 8000:8000 \
           gd
```

To run multiple containers at once with the same server above,
the `GD_JWK_OCTET` variable should be replaced
to be the same in all the instances/containers.

The default host and port mapping can be configured
with the `GD_HOST` and `GD_PORT` environment variables.

Instead of environment variables,
one can use docker secrets with the same variable name
when running in a swarm.
