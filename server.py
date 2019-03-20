#!/usr/bin/env python3
import os

from asyncpgsa import pg
from sanic import response, Sanic
from sqlalchemy import select

from models import t_user_info, t_document_hist, t_document_event


app = Sanic(__name__)


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


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000, debug=True)
