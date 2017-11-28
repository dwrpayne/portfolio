import functools


class APIResponseError(RuntimeError):
    def __init__(self, api_response):
        self.api_response = api_response

    def __str__(self):
        return 'The API request did not receive a successful response: {!r}'.format(self.api_response)


def api_response(root_key='', check_response_status=True):
    def decorator(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            response_json = fn(*args, **kwargs)
            if check_response_status and response_json['response_status']['status_code'] != 'SUCCESS':
                raise exceptions.APIResponseError(response_json)
            if not root_key:
                return response_json
            return response_json[root_key]
        return wrapper
    return decorator
