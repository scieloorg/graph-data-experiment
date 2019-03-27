# Graph data experiment

Experiment on persistent data history storage as a DAG.

The current working directory for all commands described here
is the repository root directory.

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


## Back-end setup

To install the server dependencies/requirements (frozen versions)
in a virtual environment:

```bash
python -m venv venv # Create a virtual environment
. venv/bin/activate # Activate the virtual environment
pip install -r requirements.txt
```

Or, to install the current version of the dependencies
instead of the frozen versions
(these are the direct dependencies):

```bash
pip install sanic sanic-cors sqlalchemy asyncpgsa
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
