ROUTES = {}


def route(method, path):
    def deco(fn):
        ROUTES[(method, path)] = fn
        return fn
    return deco


@route("GET", "/users")
def list_users(request):
    return 200, {"users": ["ann", "bob"]}


def handle(method, path, request=None):
    fn = ROUTES.get((method, path))
    if fn is None:
        return 404, {"error": "not found"}
    return fn(request)
