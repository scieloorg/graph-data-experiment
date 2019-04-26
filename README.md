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
docker run --rm \
           -d \
           -p 5432:5432 \
           -e POSTGRES_USER=user \
           -e POSTGRES_PASSWORD=pass \
           -e POSTGRES_DB=histdb \
           --name pgdb \
           postgres
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
export PGSQL_URL=postgres://user:pass@localhost:5432/histdb
alembic upgrade head
```

These "local" PostgreSQL credentials are the ones
from the docker call in the example.
To bootstrap this otherwhere
just replace the PGSQL_URL environment variable
with the actual credentials.


## LDAP Authentication setup

For testing the application in an isolated environment,
one can run OpenLDAP and populate it with some users.
An example using OpenLDAP v2.4.47:

```bash
LDAP_MAIN_PASSWORD=$(head -c9 /dev/urandom | hexdump -e '"%x"')

docker network create gd-network
docker run --rm \
           -d \
           -p 636:636 \
           --name gd-ldap \
           --hostname graph.data \
           --network gd-network \
           --env LDAP_ADMIN_PASSWORD="$LDAP_MAIN_PASSWORD" \
           --env LDAP_CONFIG_PASSWORD="$LDAP_MAIN_PASSWORD" \
           --env LDAP_DOMAIN="graph.data" \
           --env LDAP_ORGANISATION="Organise & Organize Company Ltd." \
           --env LDAP_TLS_VERIFY_CLIENT=try \
           osixia/openldap:1.2.4

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

Then LDAP_DSN environment variable to use with this approach is:

```bash
export LDAP_DSN="ldaps://uid=admin4gd,dc=graph,dc=data:adminpw@`
                        `localhost/ou=users,dc=graph,dc=data`
                        `?user_field=uid"
```

To manually configure this LDAP using a web UI, one can use this:

```bash
docker run --rm \
           -d \
           --name gd-ldap-admin \
           --network gd-network \
           --env PHPLDAPADMIN_LDAP_HOSTS=gd-ldap \
           osixia/phpldapadmin:0.7.2

# To show the web UI URL
GD_LDAPADMIN_IP=$(
  docker container inspect gd-ldap-admin \
  | jq -r '.[].NetworkSettings.Networks["gd-network"].IPAddress'
)
echo https://$GD_LDAPADMIN_IP
```


## Back-end setup

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
pip install sanic sanic-cors sqlalchemy asyncpgsa bonsai jwcrypto
```

To run the web server in a already activated virtual environment
(replace the PostgreSQL credentials with the actual ones):

```bash
export PGSQL_URL=postgres://user:pass@localhost:5432/histdb
./server.py
```


## Front-end setup

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
