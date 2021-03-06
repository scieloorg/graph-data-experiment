#!/usr/bin/env python3
from datetime import datetime
import os
import re

import asyncpg
from asyncpgsa import pg
from sanic import response, Sanic
from sanic_cors import CORS
from sanic_prometheus import monitor
from sqlalchemy import func, literal, select
from sqlalchemy.dialects.postgresql import insert
import ujson

from jweauth import SanicJWEAuth
from ldapauth import LDAPAuth, LDAPInvalidCredentials, LDAPUserNotFound
from models import t_user_info, t_document_hist, t_document_event, \
                   t_snapshot, SQL_UTC
from misc import nestget_str


app = Sanic(__name__)
CORS(app, automatic_options=True)
app.static("/", "client/dist/index.html")
app.static("/main.css", "client/dist/main.css")
app.static("/main.js", "client/dist/main.js")
app.static("/assets", "client/dist/assets")
ldap = LDAPAuth(os.environ["GD_LDAP_DSN"])


try:
    try:
        monitor_port = int(os.environ["GD_PROMETHEUS_PORT"])
    except (KeyError, ValueError):
        monitor(app).expose_endpoint()
    else:
        monitor(app).start_server(addr="0.0.0.0", port=monitor_port)
except OSError as exc:
    # https://github.com/prometheus/client_python/issues/155
    if exc.errno != 98:  # TODO: Remove all this OSError workaround
        raise            # after this Prometheus client bug gets fixed


class AuthError(Exception):
    pass


async def authenticate(username, password):
    if not (isinstance(username, str) and isinstance(password, str)):
        raise AuthError("Invalid data type")
    try:
        user_data = await ldap.authenticate(username, password, attrs=["cn"])
    except (LDAPInvalidCredentials, LDAPUserNotFound):
        raise AuthError("Invalid credentials")
    user_info = await pg.fetchrow(
        insert(t_user_info).values(
            uid=username,
        ).on_conflict_do_update(
            index_elements=["uid"],
            set_={"last_auth": SQL_UTC},
        )
    )
    return {
        "role": "admin",
        "name": nestget_str(user_data, "cn", 0),
    }


jwe = SanicJWEAuth(app, authenticate,
    auth_exceptions=[AuthError],
    session_fields={"uid": "sub", "role": "r", "name": "n"},
    realm="gd",
    octet=os.environ["GD_JWK_OCTET"],
)


@app.listener("before_server_start")
async def setup_db(app, loop):
    await pg.init(os.environ["GD_PGSQL_DSN"])


@app.exception(asyncpg.IntegrityConstraintViolationError)
def handle_database_integrity_constraint_violation(request, exc):
    return response.json({
        "error": re.sub(r"([^A-Z])([A-Z])", r"\1_\2",
                        type(exc).__name__).lower(),
        "constraint": exc.constraint_name,
        "table": exc.table_name,
        "column": exc.column_name,
    }, status=400)


@app.exception(asyncpg.RaiseError)
def handle_database_function_raise(request, exc):
    return response.json({"error": exc.message}, status=400)


@app.exception(asyncpg.DataError)
def handle_database_data_error(request, exc):
    # TODO: Add validators elsewhere (this might be a client error)
    return response.json({
        "error": "invalid_datatype",
        "detail": (exc.__cause__ or exc).args[0],
    }, status=500)


@app.exception(asyncpg.PostgresError)
def handle_database_exception(request, exc):
    return response.json({"error": "internal_database_error",
                          "message": exc.message}, status=500)


@app.route("/user")
@jwe.require_authorization
async def get_user(request):
    return response.json({
        "session": request["session"],
        "jwe": jwe.get_jwe(request)
    })


# TODO: Find a way to merge (multiple parents)
# TODO: Find a way to add "back history" (add events between histories)
@app.route("/document", methods=["POST"])
@app.route("/document/<parent:uuid>", methods=["POST"])
@jwe.require_authorization
async def post_document(request, parent=None):
    payload = request.json
    if "pid" not in payload or not isinstance(payload["pid"], str):
        return response.json({"error": "need_pid_string"}, status=400)
    if "title" not in payload or not isinstance(payload["title"], str):
        return response.json({"error": "need_title_string"}, status=400)
    if "published" in payload and not isinstance(payload["published"], bool):
        return response.json({"error": "invalid_published_type"}, status=400)

    async with pg.transaction() as conn:
        node = await conn.fetchrow(t_document_hist.insert().values(
            pid=payload["pid"],
            title=payload["title"],
            published=payload.get("published", False),
        ).returning(t_document_hist.c.hid, t_document_hist.c.tstamp))
        edge = await conn.fetchrow(t_document_event.insert().values(
            parent=parent,
            hist=node["hid"],
            uid=request["session"]["uid"],
            reason="insert" if parent is None else "update",
        ).returning(t_document_event.c.tstamp))
    return response.json({
        "hid": str(node["hid"]),
        "content_tstamp": node["tstamp"] and
                          node["tstamp"].strftime("%Y-%m-%dT%H:%M:%S.%fZ"),
        "action_tstamp": edge["tstamp"].strftime("%Y-%m-%dT%H:%M:%S.%fZ"),
    })


@app.route("/graph/<hid:uuid>")
async def get_graph(request, hid):
    cte_query = t_document_event.select() \
                                .where(t_document_event.c.hist == str(hid)) \
                                .cte("all_events", recursive=True)
    ref_query = cte_query.alias("ref")
    evt_query = t_document_event.alias("evt")
    full_events_query = cte_query.union(
        select(
            columns=[evt_query],
            from_obj=[ref_query, evt_query],
            whereclause=(evt_query.c.parent == ref_query.c.hist) |
                        (evt_query.c.hist == ref_query.c.parent),
        )
    ).select().order_by(cte_query.c.tstamp)

    async with pg.transaction(isolation="repeatable_read") as conn:
        edges = await conn.fetch(full_events_query)
        nodes = await conn.fetch(t_document_hist.select().where(
            t_document_hist.c.hid.in_([r["hist"] for r in edges])
        ).order_by(t_document_hist.c.tstamp))
    return response.json({
        "nodes": [{
            "hid": str(node["hid"]),
            "pid": node["pid"],
            "title": node["title"],
            "tstamp": node["tstamp"] and
                      node["tstamp"].strftime("%Y-%m-%dT%H:%M:%S.%fZ"),
        } for node in nodes],
        "edges": [{
            "parent": edge["parent"] and str(edge["parent"]),
            "hist": str(edge["hist"]),
            "reason": edge["reason"],
            "comment": edge["comment"],
            "tstamp": edge["tstamp"].strftime("%Y-%m-%dT%H:%M:%S.%fZ"),
        } for edge in edges],
    })


@app.route("/node/<hid:uuid>")
async def get_node(request, hid):
    node_query = t_document_hist.select().where(t_document_hist.c.hid == hid)
    node = await pg.fetchrow(node_query)
    if not node:
        return response.json({"error": "not_found"}, status=404)
    if node["deleted"]:
        return response.json({"error": "gone"}, status=410)
    return response.json({
        "hid": str(node["hid"]),
        "pid": node["pid"],
        "title": node["title"],
        "metadata": ujson.loads(node["metadata"]),
        "published": node["published"],
        "tstamp": node["tstamp"] and
                  node["tstamp"].strftime("%Y-%m-%dT%H:%M:%S.%fZ"),
    })


@app.route("/edge/<parent:uuid>/<hist:uuid>")
@app.route("/edge/null/<hist:uuid>")
async def get_edge_event(request, parent=None, hist=None):
    edge_query = t_document_event.select().where(
        (t_document_event.c.parent == parent) &
        (t_document_event.c.hist == hist)
    )
    edge = await pg.fetchrow(edge_query)
    if not edge:
        return response.json({"error": "not_found"}, status=404)
    return response.json({
        "parent": str(edge["parent"]),
        "hist": str(edge["hist"]),
        "uid": edge["uid"],
        "reason": edge["reason"],
        "comment": edge["comment"],
        "tstamp": edge["tstamp"] and
                  edge["tstamp"].strftime("%Y-%m-%dT%H:%M:%S.%fZ"),
    })


@app.route("/node/<hid:uuid>", methods=["PATCH"])
@jwe.require_authorization
async def patch_node(request, hid):
    await pg.fetchrow(t_document_hist.update().values(
        **request.json # TODO: validate the input
    ).where(t_document_hist.c.hid == hid))
    return response.json({"status": "updated"})


@app.route("/edge/<parent:uuid>/<hist:uuid>", methods=["PATCH"])
@app.route("/edge/null/<hist:uuid>", methods=["PATCH"])
@jwe.require_authorization
async def patch_edge_event(request, parent=None, hist=None):
    await pg.fetchrow(t_document_event.update().values(
        **request.json # TODO: validate the input
    ).where(
        (t_document_event.c.parent == parent) &
        (t_document_event.c.hist == hist)
    ))
    return response.json({"status": "updated"})


@app.route("/node/<hid:uuid>", methods=["DELETE"])
@jwe.require_authorization
async def delete_node(request, hid):
    str_result = await pg.execute(
        t_document_hist.delete().where(t_document_hist.c.hid == hid)
    )
    deleted_count = int(str_result.split()[1])
    if deleted_count == 0:
        return response.json({"error": "not_found"}, status=404)
    return response.json({"status": "deleted"})


@app.route("/edge/<parent:uuid>/<hist:uuid>", methods=["DELETE"])
@app.route("/edge/null/<hist:uuid>", methods=["DELETE"])
@jwe.require_authorization
async def delete_edge_event(request, parent=None, hist=None):
    str_result = await pg.fetch(t_document_event.delete().where(
        (t_document_event.c.parent == parent) &
        (t_document_event.c.hist == hist)
    ))
    deleted_count = int(str_result.split()[1])
    if deleted_count == 0:
        return response.json({"error": "not_found"}, status=404)
    return response.json({"status": "deleted"})


@app.route("/node", methods=["POST"])
@jwe.require_authorization
async def post_node(request):
    node_query = t_document_hist.insert().values(
        **request.json # TODO: validate the input
    ).returning(t_document_hist.c.hid)
    node = await pg.fetchrow(node_query)
    return response.json({
        "status": "inserted",
        "hid": str(node["hid"]),
    })

@app.route("/edge/<parent:uuid>/<hist:uuid>", methods=["POST"])
@app.route("/edge/null/<hist:uuid>", methods=["POST"])
@jwe.require_authorization
async def post_edge_event(request, parent=None, hist=None):
    await pg.fetchrow(t_document_event.insert().values(
        parent=parent,
        hist=hist,
        **request.json # TODO: validate the input
    ))
    return response.json({"status": "inserted"})


@app.route("/node/<hid:uuid>", methods=["PUT"])
@jwe.require_authorization
async def put_node(request, hid):
    async with pg.transaction() as conn:
        await conn.execute(
            t_document_hist.delete().where(t_document_hist.c.hid == hid)
        )
        node = await conn.fetchrow(t_document_hist.insert().values(
            **request.json # TODO: validate the input
        ).returning(t_document_hist.c.hid))
    return response.json({
        "status": "replaced",
        "hid": str(node["hid"]),
    })


@app.route("/edge/<parent:uuid>/<hist:uuid>", methods=["PUT"])
@app.route("/edge/null/<hist:uuid>", methods=["PUT"])
@jwe.require_authorization
async def put_edge_event(request, parent=None, hist=None):
    async with pg.transaction() as conn:
        await conn.execute(t_document_event.delete().where(
            (t_document_event.c.parent == parent) &
            (t_document_event.c.hist == hist)
        ))
        await conn.fetchrow(t_document_event.insert().values(
            parent=parent,
            hist=hist,
            **request.json # TODO: validate the input
        ))
    return response.json({"status": "replaced"})


@app.route("/node")
@jwe.require_authorization
async def get_nodes(request):
    get_nodes_query = select([t_document_hist.c.hid])
    nodes = await pg.fetch(get_nodes_query)
    return response.json({"nodes": [str(node["hid"]) for node in nodes]})


@app.route("/edge")
@jwe.require_authorization
async def get_edges(request):
    get_edges_query = select([t_document_event.c.parent,
                              t_document_event.c.hist])
    edges = await pg.fetch(get_edges_query)
    return response.json({"edges": [{
        "parent": edge["parent"] and str(edge["parent"]),
        "hist": str(edge["hist"]),
    } for edge in edges]})


@app.route("/snapshot", methods=["POST"])
@jwe.require_authorization
async def post_snapshot(request):
    if not request.json or "uid" in request.json:
        return response.json({"error": "invalid_snapshot"}, status=400)
    data = {**request.json, "uid": request["session"]["uid"]}
    if "tstamp" in data:
        data["tstamp"] = datetime.fromtimestamp(data["tstamp"])
    query = t_snapshot.insert().values(**data).returning(t_snapshot.c.tstamp)
    snapshot = await pg.fetchrow(query)
    return response.json({
        "status": "inserted",
        "tstamp": snapshot["tstamp"].strftime("%Y-%m-%dT%H:%M:%S.%fZ"),
    })


@app.route("/snapshot/batch", methods=["POST"])
@jwe.require_authorization
async def post_snapshot_batch(request):
    rows = []
    for row in request.body.splitlines():
        unicode_row = row.strip().decode("utf-8")
        if unicode_row:
            row_data = ujson.loads(unicode_row)
            if "uid" in row_data:
                return response.json({"error": "invalid_snapshot"}, status=400)
            data = {**row_data, "uid": request["session"]["uid"]}
            if "tstamp" in data:
                data["tstamp"] = datetime.fromtimestamp(data["tstamp"])
            rows.append(data)
    if rows:
        query = select(
            columns=[func.count()],
            from_obj=insert(t_snapshot).values(rows)
                                       .on_conflict_do_nothing()
                                       .returning(literal("1"))
                                       .cte("rows"),
        )
        snapshot_count = await pg.fetchval(query)
    else:
        snapshot_count = 0
    return response.json({
        "status": "inserted",
        "count": snapshot_count,
    })


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000, debug=True)
