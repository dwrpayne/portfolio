import functools


class APIResponseError(RuntimeError):
    def __init__(self, resp):
        self.api_response = resp

    def __str__(self):
        return 'The API request did not receive a successful response: {!r}'.format(self.api_response)


def api_response(root_key='', check_response_fn=None):
    """
    Decorate an api response function that returns json with this.
    :param root_key: The root json key.
    :param check_response_fn: An option function to evaluate api success.
                    If it returns false, throw APIResponseError
    :return: The value of the json at root key.
    """
    def decorator(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            response_json = fn(*args, **kwargs)
            if check_response_fn and not check_response_fn(response_json):
                raise APIResponseError(response_json)
            if not root_key:
                return response_json
            return response_json[root_key]
        return wrapper
    return decorator
