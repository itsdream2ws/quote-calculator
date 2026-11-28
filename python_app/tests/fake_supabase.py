"""A pretend Supabase, for tests only. It answers the same web addresses the app uses
(/auth/v1/token, /rest/v1/<table>...) and keeps the tables in memory.

It copies the parts of Supabase the app relies on: logging in, refresh tokens, needing a
login token for every table, upsert on a key, unique quote/invoice numbers (error 23505),
and agent_profiles taking the user id and email from the login.
"""
import json
import secrets
import time

from flask import Flask, jsonify, request

KEYS = {"tickets": "code", "transport_items": "id", "guide_items": "id", "quotes": "id", "invoices": "id",
        "agent_profiles": "user_id", "settings": "id"}
UNIQUE = {"quotes": "quote_number", "invoices": "invoice_number", "transport_items": "code", "guide_items": "code"}


def make_fake(users):
    """users: {"ag01@agents.local": "password", ...}"""
    app = Flask("fake_supabase")
    app.tables = {t: [] for t in KEYS}
    app.tokens = {}          # access token -> user
    app.refresh = {}         # refresh token -> user
    app.users = {email: {"id": f"user-{i}", "email": email, "password": pw} for i, (email, pw) in enumerate(users.items())}
    app.online = True        # set to False to pretend the internet is down (answers 503)
    app.calls = []

    def issue(user):
        access, refresh = secrets.token_hex(8), secrets.token_hex(8)
        app.tokens[access] = user
        app.refresh[refresh] = user
        return {"access_token": access, "refresh_token": refresh, "expires_in": 3600,
                "expires_at": int(time.time()) + 3600, "user": {"id": user["id"], "email": user["email"]}}

    def who():
        token = request.headers.get("Authorization", "")[7:]
        return app.tokens.get(token)

    @app.before_request
    def gate():
        app.calls.append((request.method, request.path, request.query_string.decode()))
        if not app.online:
            return "down", 503
        if request.headers.get("apikey") is None:
            return jsonify({"message": "No API key found in request"}), 401

    @app.post("/auth/v1/token")
    def token():
        body = request.get_json()
        if request.args.get("grant_type") == "password":
            u = app.users.get(body.get("email"))
            if not u or u["password"] != body.get("password"):
                return jsonify({"error_code": "invalid_credentials", "msg": "Invalid login credentials"}), 400
            return jsonify(issue(u))
        u = app.refresh.pop(body.get("refresh_token"), None)
        if not u:
            return jsonify({"error_code": "refresh_token_not_found", "msg": "Invalid Refresh Token"}), 400
        return jsonify(issue(u))

    @app.put("/auth/v1/user")
    def user_update():
        u = who()
        if not u:
            return jsonify({"msg": "JWT expired"}), 401
        u["password"] = request.get_json()["password"]
        return jsonify({"id": u["id"]})

    @app.post("/auth/v1/logout")
    def logout():
        return "", 204

    @app.route("/rest/v1/<table>", methods=["GET", "POST", "DELETE"])
    def rest(table):
        u = who()
        if not u:
            return jsonify({"code": "42501", "message": "permission denied for table " + table}), 401
        rows = app.tables[table]
        if request.method == "GET":
            out = rows
            for k, v in request.args.items():
                if v.startswith("eq."):
                    out = [r for r in out if str(r.get(k)) == v[3:]]
            order = request.args.get("order")
            if order:
                out = sorted(out, key=lambda r: str(r.get(order)))
            off, lim = int(request.args.get("offset", 0)), int(request.args.get("limit", 1000))
            out = out[off:off + lim]
            if request.args.get("select") == "data":
                out = [{"data": r["data"]} for r in out]
            return jsonify(out)
        if request.method == "DELETE":
            (k, v), = [(k, v) for k, v in request.args.items()]
            app.tables[table] = [r for r in rows if str(r.get(k)) != v[3:]]
            return "", 204
        key = request.args.get("on_conflict") or KEYS[table]
        for new in request.get_json():
            new = json.loads(json.dumps(new))
            if table == "agent_profiles":  # the database's trigger: owner comes from the login
                new["user_id"], new["email"] = u["id"], u["email"]
            uniq = UNIQUE.get(table)
            if uniq and new.get(uniq) and any(r.get(uniq) == new[uniq] and r[key] != new[key] for r in rows):
                return jsonify({"code": "23505", "message": f'duplicate key value violates unique constraint "{table}_{uniq}_key"'}), 409
            old = next((r for r in rows if r[key] == new[key]), None)
            if old:
                old.update(new)
            else:
                rows.append(new)
        return "", 201

    return app
