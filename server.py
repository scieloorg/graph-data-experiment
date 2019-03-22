#!/usr/bin/env python3
import os

from asyncpgsa import pg
from sanic import response, Sanic
from sanic_cors import CORS
from sqlalchemy import select

from models import t_user_info, t_document_hist, t_document_event


app = Sanic(__name__)
CORS(app, automatic_options=True)
app.static("/", "dist/index.html")
app.static("/main.css", "dist/main.css")
app.static("/main.js", "dist/main.js")


@app.listener("before_server_start")
async def setup_db(app, loop):
    await pg.init(os.environ["PGSQL_URL"])


@app.route("/user", methods=["POST"])
async def post_user(request):
    if len(request.json) != 1 or "name" not in request.json \
                              or not isinstance(request.json["name"], str):
        return response.json({"error": "need_single_name_string"}, status=400)
    name = request.json["name"]
    user = await pg.fetchrow(
        t_user_info.insert()
                   .values(name=name)
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
async def post_document(request, parent=None):
    payload = request.json
    if "pid" not in payload or not isinstance(payload["pid"], str):
        return response.json({"error": "need_pid_string"}, status=400)
    if "title" not in payload or not isinstance(payload["title"], str):
        return response.json({"error": "need_title_string"}, status=400)

    # TODO: Unhardcode the user
    uid_query = select([t_user_info.c.uid]) \
                .where(t_user_info.c.name == "danilo")
    async with pg.transaction() as conn:
        node = await conn.fetchrow(t_document_hist.insert().values(
            pid=payload["pid"],
            title=payload["title"],
        ).returning(t_document_hist.c.hid, t_document_hist.c.tstamp))
        edge = await conn.fetchrow(t_document_event.insert().values(
            parent=parent,
            hist=node["hid"],
            uid=uid_query,
            reason="insert" if parent is None else "update",
        ).returning(t_document_event.c.tstamp))
    return response.json({
        "hid": str(node["hid"]),
        "content_tstamp": node["tstamp"].strftime("%Y-%m-%dT%H:%M:%S.%fZ"),
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
        edges = await pg.fetch(full_events_query)
        nodes = await pg.fetch(t_document_hist.select().where(
            t_document_hist.c.hid.in_([r["hist"] for r in edges])
        ).order_by(t_document_hist.c.tstamp))
        print(edges)
        print(nodes)
    return response.json({
        "nodes": [{
            "hid": str(node["hid"]),
            "pid": node["pid"],
            "title": node["title"],
            "tstamp": node["tstamp"].strftime("%Y-%m-%dT%H:%M:%S.%fZ"),
        } for node in nodes],
        "edges": [{
            "parent": edge["parent"] and str(edge["parent"]),
            "hist": str(edge["hist"]),
            "reason": edge["reason"],
            "comment": edge["comment"],
            "tstamp": edge["tstamp"].strftime("%Y-%m-%dT%H:%M:%S.%fZ"),
        } for edge in edges],
    })


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000, debug=True)
