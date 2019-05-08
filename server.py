#!/usr/bin/env python3
import os
import re

import asyncpg
from asyncpgsa import pg
from sanic import response, Sanic
from sanic_cors import CORS
from sqlalchemy import select
import ujson

from jweauth import SanicJWEAuth
from ldapauth import LDAPAuth, LDAPInvalidCredentials, LDAPUserNotFound
from models import t_user_info, t_document_hist, t_document_event


app = Sanic(__name__)
CORS(app, automatic_options=True)
app.static("/", "dist/index.html")
app.static("/main.css", "dist/main.css")
app.static("/main.js", "dist/main.js")
ldap = LDAPAuth(os.environ["GD_LDAP_DSN"])


async def authenticate(username, password):
    await ldap.authenticate(username, password)
    return {}


jwe = SanicJWEAuth(app, authenticate,
    auth_exceptions=[LDAPInvalidCredentials, LDAPUserNotFound, TypeError],
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


@app.route("/user", methods=["POST"])
async def post_user(request):
    if len(request.json) != 1 or "name" not in request.json \
                              or not isinstance(request.json["name"], str):
        return response.json({"error": "need_single_name_string"}, status=400)
    name = request.json["name"]
    user = await pg.fetchrow(
        t_user_info.insert()
                   .values(name=name,
                           ldap_cn="", # TODO: Replace this by LDAP
                           uid=name)
                   .returning(t_user_info.c.uid, t_user_info.c.tstamp)
    )
    return response.json({
        "name": name,
        "uid": str(user["uid"]),
        "tstamp": user["tstamp"].strftime("%Y-%m-%dT%H:%M:%S.%fZ"),
    }
)


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
            uid="danilo", # TODO: Unhardcode this
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


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000, debug=True)
